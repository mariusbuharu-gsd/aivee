// The AiVee eyes follow the pointer: the mouse on desktop, the finger while it touches the screen.
// Progressive enhancement: every <img data-eyes> is swapped for its inline SVG so the pupils can move;
// without JS (or if the fetch fails) the plain image stays. Reduced motion keeps the resting pose.

const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
const SVG_NS = "http://www.w3.org/2000/svg";
const RETURN_AFTER_MS = 1800; // idle time before the eyes go back to their resting glance
const REACH_PX = 160; // pointer distance at which a pupil reaches the edge of its eye
const EASE = 0.18; // per-frame smoothing

/** @type {{pupil: SVGCircleElement, svg: SVGSVGElement, cx: number, cy: number, max: number, rest: [number, number], now: [number, number]}[]} */
const pupils = [];
let pointer = null; // {x, y} in client pixels, or null when idle
let idleTimer = 0;
let frame = 0;

async function inline(img) {
  const res = await fetch(img.getAttribute("src"));
  if (!res.ok) return;
  const doc = new DOMParser().parseFromString(await res.text(), "image/svg+xml");
  const svg = doc.documentElement;
  if (svg.namespaceURI !== SVG_NS) return;
  svg.setAttribute("width", img.getAttribute("width") ?? "");
  svg.setAttribute("height", img.getAttribute("height") ?? "");
  svg.setAttribute("class", `${img.className} eyes`.trim());
  if (img.alt) svg.setAttribute("aria-label", img.alt);
  else {
    svg.removeAttribute("role");
    svg.removeAttribute("aria-label");
    svg.setAttribute("aria-hidden", "true");
  }
  const node = document.importNode(svg, true);
  img.replaceWith(node);

  // Eyes are drawn as ring + pupil pairs: an unfilled circle followed by the filled one inside it.
  const circles = [...node.querySelectorAll("circle")];
  for (let i = 0; i + 1 < circles.length; i += 2) {
    const ring = circles[i];
    const pupil = circles[i + 1];
    const cx = +ring.getAttribute("cx");
    const cy = +ring.getAttribute("cy");
    const ringR = +ring.getAttribute("r");
    const stroke = +(ring.getAttribute("stroke-width") ?? 0);
    const pupilR = +pupil.getAttribute("r");
    const rest = [+pupil.getAttribute("cx") - cx, +pupil.getAttribute("cy") - cy];
    pupil.setAttribute("cx", String(cx));
    pupil.setAttribute("cy", String(cy));
    pupil.setAttribute("transform", `translate(${rest[0]} ${rest[1]})`);
    pupils.push({ pupil, svg: node, cx, cy, max: ringR - stroke / 2 - pupilR - 0.5, rest, now: [...rest] });
  }
}

function target(p) {
  if (!pointer) return p.rest;
  // Map the eye centre from SVG units to client pixels through the element's current box.
  const box = p.svg.getBoundingClientRect();
  const vb = p.svg.viewBox.baseVal;
  const scale = box.width / vb.width;
  const ex = box.left + (p.cx - vb.x) * scale;
  const ey = box.top + (p.cy - vb.y) * scale;
  const dx = pointer.x - ex;
  const dy = pointer.y - ey;
  const dist = Math.hypot(dx, dy);
  if (dist < 1) return [0, 0];
  const reach = Math.min(1, dist / REACH_PX) * p.max;
  return [(dx / dist) * reach, (dy / dist) * reach];
}

function tick() {
  frame = 0;
  let moving = false;
  for (const p of pupils) {
    const [tx, ty] = target(p);
    p.now[0] += (tx - p.now[0]) * EASE;
    p.now[1] += (ty - p.now[1]) * EASE;
    if (Math.abs(tx - p.now[0]) > 0.02 || Math.abs(ty - p.now[1]) > 0.02) moving = true;
    p.pupil.setAttribute("transform", `translate(${p.now[0].toFixed(2)} ${p.now[1].toFixed(2)})`);
  }
  if (moving || pointer) frame = requestAnimationFrame(tick);
}

function wake() {
  if (!frame) frame = requestAnimationFrame(tick);
}

function look(x, y) {
  pointer = { x, y };
  clearTimeout(idleTimer);
  idleTimer = window.setTimeout(rest, RETURN_AFTER_MS);
  wake();
}

function rest() {
  pointer = null;
  wake();
}

async function start() {
  const imgs = [...document.querySelectorAll("img[data-eyes]")];
  await Promise.all(imgs.map((img) => inline(img).catch(() => undefined)));
  if (!pupils.length) return;

  window.addEventListener("pointermove", (e) => look(e.clientX, e.clientY), { passive: true });
  window.addEventListener("pointerdown", (e) => look(e.clientX, e.clientY), { passive: true });
  window.addEventListener(
    "touchmove",
    (e) => {
      const t = e.touches[0];
      if (t) look(t.clientX, t.clientY);
    },
    { passive: true },
  );
  window.addEventListener("touchend", () => {
    clearTimeout(idleTimer);
    idleTimer = window.setTimeout(rest, 600);
  });
  document.documentElement.addEventListener("pointerleave", rest);
  window.addEventListener("blur", rest);
}

if (!reduce.matches) start();
