"""How long an uploaded clip is, checked before it is queued."""

from pathlib import Path


class UnreadableVideo(ValueError):
    """The file is not a video OpenCV can decode."""


def probe_duration(path: Path) -> float | None:
    """Length in seconds via OpenCV, or None when OpenCV is not installed (the slim API
    image): the run itself still stops a clip that is too long."""
    try:
        import cv2
    except ImportError:
        return None
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise UnreadableVideo(str(path))
        fps = cap.get(cv2.CAP_PROP_FPS)
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        if not fps or fps <= 0 or not frames or frames <= 0:
            ok, _ = cap.read()
            if not ok:
                raise UnreadableVideo(str(path))
            return None
        return float(frames / fps)
    finally:
        cap.release()
