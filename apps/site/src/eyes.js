// The AiVee eyes follow the pointer: the mouse on desktop, the finger while it touches the screen.
// Progressive enhancement: every <img data-eyes> is swapped for its inline SVG so the pupils can
// move; inline <svg data-eyes> (the big hero eyes) is used as is. Without JS, or with reduced
// motion, every eye keeps its drawn pose.
//
// - Circular clamp: a pupil travels the same distance in every direction and never touches the
//   ring (ring radius − stroke/2 − pupil radius − a 6% gap).
// - Rest pose: the logo keeps its drawn glance (down and right); [data-eyes-hold] eyes rest in the
//   centre. [data-eyes-frozen] (set by story.js during the hero dive) sends pupils to the centre.
// - Input handlers only store coordinates; one requestAnimationFrame loop eases the pupils and
//   sleeps when idle, when the eyes are off-screen and while the tab is hidden.

const SVG_NS = "http://www.w3.org/2000/svg";
const RETURN_AFTER_MS = 1800; // idle time before the eyes go back to their resting glance
const FOLLOW = 0.35; // svg units of travel per svg unit of pointer distance, before the clamp
const EASE = 0.18; // per-frame smoothing

/** @type {{svg: SVGSVGElement, seen: boolean, pupils: {pupil: SVGCircleElement, cx: number, cy: number, max: number, rest: number[], now: number[]}[]}[]} */
const sets = [];
let pointer = null;
let idleTimer = 0;
let frame = 0;

async function inline(img) {
  const res = await fetch(img.getAttribute("src"));
  if (!res.ok) return null;
  const doc = new DOMParser().parseFromString(await res.text(), "image/svg+xml");
  const svg = doc.documentElement;
  if (svg.namespaceURI !== SVG_NS) return null;
  svg.setAttribute("width", img.getAttribute("width") ?? "");
  svg.setAttribute("height", img.getAttribute("height") ?? "");
  if (img.alt) svg.setAttribute("aria-label", img.alt);
  else {
    svg.removeAttribute("role");
    svg.removeAttribute("aria-label");
    svg.setAttribute("aria-hidden", "true");
  }
  const node = /** @type {SVGSVGElement} */ (document.importNode(svg, true));
  img.replaceWith(node);
  return node;
}

/** Eyes are drawn as ring + pupil pairs: an unfilled circle followed by the filled one inside it. */
function register(svg) {
  const circles = [...svg.querySelectorAll("circle")];
  const set = { svg, seen: true, pupils: [] };
  for (let i = 0; i + 1 < circles.length; i += 2) {
    const ring = circles[i];
    const pupil = circles[i + 1];
    const cx = +ring.getAttribute("cx");
    const cy = +ring.getAttribute("cy");
    const stroke = parseFloat(ring.getAttribute("stroke-width") || getComputedStyle(ring).strokeWidth) || 0;
    const inner = +ring.getAttribute("r") - stroke / 2;
    const max = inner - +pupil.getAttribute("r") - inner * 0.06;
    let rest = svg.hasAttribute("data-eyes-hold")
      ? [0, 0]
      : [+pupil.getAttribute("cx") - cx, +pupil.getAttribute("cy") - cy];
    const len = Math.hypot(rest[0], rest[1]);
    if (len > max) rest = [(rest[0] / len) * max, (rest[1] / len) * max];
    pupil.setAttribute("cx", String(cx));
    pupil.setAttribute("cy", String(cy));
    pupil.setAttribute("transform", `translate(${rest[0]} ${rest[1]})`);
    set.pupils.push({ pupil, cx, cy, max, rest, now: [...rest] });
  }
  if (set.pupils.length) sets.push(set);
}

function tick() {
  frame = 0;
  let moving = false;
  for (const set of sets) {
    if (!set.seen) continue;
    const frozen = set.svg.hasAttribute("data-eyes-frozen");
    const box = pointer && !frozen ? set.svg.getBoundingClientRect() : null; // once per svg per frame
    const vb = set.svg.viewBox.baseVal;
    const k = box ? box.width / vb.width : 1;
    for (const p of set.pupils) {
      let [tx, ty] = frozen ? [0, 0] : p.rest;
      if (box) {
        // Pointer offset from the eye centre, in svg units.
        const dx = (pointer.x - (box.left + (p.cx - vb.x) * k)) / k;
        const dy = (pointer.y - (box.top + (p.cy - vb.y) * k)) / k;
        const d = Math.hypot(dx, dy);
        const r = Math.min(d * FOLLOW, p.max);
        [tx, ty] = d > 0.01 ? [(dx / d) * r, (dy / d) * r] : [0, 0];
      }
      p.now[0] += (tx - p.now[0]) * EASE;
      p.now[1] += (ty - p.now[1]) * EASE;
      if (Math.abs(tx - p.now[0]) > 0.01 || Math.abs(ty - p.now[1]) > 0.01) moving = true;
      p.pupil.setAttribute("transform", `translate(${p.now[0].toFixed(2)} ${p.now[1].toFixed(2)})`);
    }
  }
  if ((moving || pointer) && !document.hidden) frame = requestAnimationFrame(tick);
}

export function wake() {
  if (!frame && !document.hidden) frame = requestAnimationFrame(tick);
}

function look(x, y, after = RETURN_AFTER_MS) {
  pointer = { x, y };
  clearTimeout(idleTimer);
  idleTimer = window.setTimeout(rest, after);
  wake();
}

function rest() {
  pointer = null;
  wake();
}

async function start() {
  const imgs = [...document.querySelectorAll("img[data-eyes]")];
  const inlined = await Promise.all(imgs.map((img) => inline(img).catch(() => null)));
  for (const svg of [...document.querySelectorAll("svg[data-eyes]")]) register(svg);
  if (!sets.length || !inlined) return;

  const seen = new IntersectionObserver((entries) => {
    for (const e of entries) {
      const set = sets.find((s) => s.svg === e.target);
      if (set) set.seen = e.isIntersecting;
    }
  });
  for (const set of sets) seen.observe(set.svg);

  const touch = (e) => {
    const t = e.touches[0];
    if (t) look(t.clientX, t.clientY);
  };
  addEventListener("pointermove", (e) => look(e.clientX, e.clientY), { passive: true });
  addEventListener("pointerdown", (e) => look(e.clientX, e.clientY), { passive: true });
  addEventListener("touchstart", touch, { passive: true });
  addEventListener("touchmove", touch, { passive: true });
  addEventListener("touchend", () => {
    clearTimeout(idleTimer);
    idleTimer = window.setTimeout(rest, 900);
  });
  document.documentElement.addEventListener("pointerleave", rest);
  addEventListener("blur", rest);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      cancelAnimationFrame(frame);
      frame = 0;
    } else wake();
  });
  // Test hook for the screenshot scripts: aim the eyes at a point.
  window.__eyesLook = look;
}

if (!matchMedia("(prefers-reduced-motion: reduce)").matches) start();
