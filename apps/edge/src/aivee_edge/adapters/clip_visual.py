"""Zero-shot CLIP scoring for `visual` conditions, behind the domain's `VisualScorer` port.

`ClipVisualScorer` is the synchronous model: it reuses the appearance embedder's open_clip
weights (`load_clip`), adds the text encoder, caches one L2-normalised embedding per
prompt, and scores a crop as the softmax share of the positive prompts, with the model's
own temperature (`logit_scale`, 100 for ViT-B-32 laion2b).

Two port implementations wrap it:
- `BackgroundVisualScorer` (live): one worker thread, at most one frame in flight, so the
  ~0.1 s image encode never stalls the 12-15 fps pipeline; the model loads lazily on the
  worker when the first visual rule arrives.
- `InlineVisualScorer` (offline clip runs and the probe): scores inside `submit`, so a
  clip analysed faster than real time still gets every sample.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any

from aivee_edge.domain.observation import BBox
from aivee_edge.domain.visual import VisualJob, VisualSample, positive_share

log = logging.getLogger("aivee_edge.visual")


def crop_box(image: Any, box: BBox | None) -> Any:
    """The normalised `box` of a HxWxC array (the whole image for None or a degenerate box)."""
    if box is None:
        return image
    h, w = image.shape[:2]
    x1, y1, x2, y2 = box
    left, top = max(0, int(x1 * w)), max(0, int(y1 * h))
    right, bottom = min(w, round(x2 * w)), min(h, round(y2 * h))
    if right - left < 8 or bottom - top < 8:
        return image
    return image[top:bottom, left:right]


class ClipVisualScorer:
    """Synchronous CLIP scorer. Images are BGR uint8 arrays (OpenCV layout)."""

    def __init__(self, model: str | None = None, pretrained: str | None = None) -> None:
        import open_clip
        import torch

        from aivee_edge.adapters.clip_embedder import CLIP_MODEL, CLIP_PRETRAINED, load_clip

        name = model or CLIP_MODEL
        self._torch = torch
        self._model, self._preprocess = load_clip(name, pretrained or CLIP_PRETRAINED)
        self._tokenizer = open_clip.get_tokenizer(name)
        self._scale = float(self._model.logit_scale.exp().item())
        self._text: dict[str, Any] = {}

    @property
    def logit_scale(self) -> float:
        return self._scale

    def prepare(self, prompts: Sequence[str]) -> None:
        new = [p for p in dict.fromkeys(prompts) if p not in self._text]
        if not new:
            return
        with self._torch.inference_mode():
            features = self._model.encode_text(self._tokenizer(new))
            features = features / features.norm(dim=-1, keepdim=True)
        for prompt, vec in zip(new, features, strict=True):
            self._text[prompt] = vec

    def embed_image(self, image: Any) -> Any:
        from PIL import Image

        rgb = image[:, :, ::-1]
        tensor = self._preprocess(Image.fromarray(rgb.copy())).unsqueeze(0)
        with self._torch.inference_mode():
            features = self._model.encode_image(tensor)[0]
            return features / features.norm()

    def score_embedding(
        self, image_vec: Any, positive: Sequence[str], negative: Sequence[str]
    ) -> float:
        prompts = [*positive, *negative]
        self.prepare(prompts)
        text = self._torch.stack([self._text[p] for p in prompts])
        logits = (self._scale * (text @ image_vec)).tolist()
        return positive_share(logits, len(positive))

    def score(
        self, image: Any, box: BBox | None, positive: Sequence[str], negative: Sequence[str]
    ) -> float:
        return self.score_embedding(self.embed_image(crop_box(image, box)), positive, negative)

    def score_jobs(self, ts: float, image: Any, jobs: Sequence[VisualJob]) -> list[VisualSample]:
        """Every job of one frame; one image encode per distinct crop."""
        embedded: dict[BBox | None, Any] = {}
        out: list[VisualSample] = []
        for job in jobs:
            if job.box not in embedded:
                embedded[job.box] = self.embed_image(crop_box(image, job.box))
            score = self.score_embedding(embedded[job.box], job.positive, job.negative)
            out.append(VisualSample(ts, job.key, score))
        return out


ScorerFactory = Callable[[], ClipVisualScorer]


class InlineVisualScorer:
    """`VisualScorer` port that scores inside `submit` (deterministic, blocks the caller)."""

    def __init__(self, factory: ScorerFactory = ClipVisualScorer) -> None:
        self._factory = factory
        self._inner: ClipVisualScorer | None = None
        self._done: list[VisualSample] = []

    def _model(self) -> ClipVisualScorer:
        if self._inner is None:
            self._inner = self._factory()
        return self._inner

    def prepare(self, prompts: Sequence[str]) -> None:
        self._model().prepare(prompts)

    def submit(self, ts: float, image: Any, jobs: Sequence[VisualJob]) -> bool:
        self._done += self._model().score_jobs(ts, image, jobs)
        return True

    def collect(self) -> list[VisualSample]:
        done, self._done = self._done, []
        return done


class BackgroundVisualScorer:
    """`VisualScorer` port running CLIP on one worker thread, one frame at a time.

    `submit` returns False while the previous frame is still being scored (the engine
    tries again on the next frame). A failure is logged and its frame yields no sample.
    The worker logs `visual_score ms=… jobs=… scores=…` at most every `log_every_s` at INFO
    (every frame at DEBUG).
    """

    def __init__(self, factory: ScorerFactory = ClipVisualScorer, log_every_s: float = 5.0) -> None:
        self._factory = factory
        self._log_every_s = log_every_s
        self._logged_at = -float("inf")
        self._tasks: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._lock = threading.Lock()
        self._done: list[VisualSample] = []
        self._busy = False
        self._thread: threading.Thread | None = None
        self.last_ms: float | None = None
        """Wall time of the latest frame's scoring, for logs and benchmarks."""

    def _ensure_thread(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._work, name="visual", daemon=True)
            self._thread.start()

    def prepare(self, prompts: Sequence[str]) -> None:
        self._ensure_thread()
        self._tasks.put(("prepare", list(prompts)))

    def submit(self, ts: float, image: Any, jobs: Sequence[VisualJob]) -> bool:
        with self._lock:
            if self._busy:
                return False
            self._busy = True
        self._ensure_thread()
        # The pipeline never mutates a frame after reading it, so no copy is needed.
        self._tasks.put(("score", (ts, image, list(jobs))))
        return True

    def collect(self) -> list[VisualSample]:
        with self._lock:
            done, self._done = self._done, []
        return done

    def close(self) -> None:
        if self._thread is not None:
            self._tasks.put(("stop", None))

    def _work(self) -> None:
        inner: ClipVisualScorer | None = None
        while True:
            kind, payload = self._tasks.get()
            if kind == "stop":
                return
            try:
                if inner is None:
                    started = time.monotonic()
                    inner = self._factory()
                    log.info("visual_model_loaded seconds=%.1f", time.monotonic() - started)
                if kind == "prepare":
                    inner.prepare(payload)
                    continue
                ts, image, jobs = payload
                started = time.monotonic()
                samples = inner.score_jobs(ts, image, jobs)
                self.last_ms = (time.monotonic() - started) * 1000
                now = time.monotonic()
                level = (
                    logging.INFO if now - self._logged_at >= self._log_every_s else logging.DEBUG
                )
                if level == logging.INFO:
                    self._logged_at = now
                log.log(
                    level,
                    "visual_score ms=%.0f jobs=%d scores=%s",
                    self.last_ms,
                    len(jobs),
                    ",".join(f"{s.key[0]}/{s.key[1]}={s.score:.2f}" for s in samples),
                )
                with self._lock:
                    self._done += samples
            except Exception:
                log.exception("visual scoring failed")
            finally:
                if kind == "score":
                    with self._lock:
                        self._busy = False
