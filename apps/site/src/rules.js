// "Cum funcționează": the logo eyes read the request left to right. Where they stop, the phrase
// they understood is underlined and drops into a chip below, then they look down at the result.
// The HTML already shows the finished state, so without JS or with reduced motion nothing moves
// and nothing is missing. No library: a few timeouts and CSS transitions.

const root = document.documentElement;
const figure = document.querySelector(".reader");

if (figure && root.classList.contains("motion")) {
  const svg = figure.querySelector(".reader__eyes");
  const pupils = [...svg.querySelectorAll(".pupil")];
  const keys = [...figure.querySelectorAll(".k")];
  const chips = [...figure.querySelectorAll(".chip")];
  const CENTRES = [29, 71]; // ring centres in viewBox units, cy = 50
  const MAX = 7.5; // inner ring radius 15.5 minus pupil 8: the pupil never touches the ring
  const wait = (ms) => new Promise((done) => setTimeout(done, ms));

  /** Turn both pupils toward a point on screen, inside the ring. */
  function look(x, y) {
    const box = svg.getBoundingClientRect();
    const vb = svg.viewBox.baseVal;
    const k = box.width / vb.width;
    pupils.forEach((pupil, i) => {
      const dx = (x - (box.left + (CENTRES[i] - vb.x) * k)) / k;
      const dy = (y - (box.top + (50 - vb.y) * k)) / k;
      const d = Math.hypot(dx, dy) || 1;
      const r = Math.min(d * 0.35, MAX);
      pupil.style.transform = `translate(${(dx / d) * r}px, ${(dy / d) * r}px)`;
    });
  }
  const lookAt = (el) => {
    const r = el.getBoundingClientRect();
    look(r.left + r.width / 2, r.top + r.height / 2);
  };

  for (const p of pupils) p.style.transition = "transform .35s cubic-bezier(.3, .7, .2, 1)";

  // Rewind now: the section starts well below the fold, so the reset is never seen.
  keys.forEach((k) => k.classList.remove("hit"));
  chips.forEach((c) => c.classList.add("is-wait"));

  async function read() {
    lookAt(figure.querySelector(".reader__text"));
    await wait(500);
    for (const key of keys) {
      lookAt(key);
      await wait(420);
      key.classList.add("hit");
      chips[Number(key.dataset.i)].classList.remove("is-wait");
      await wait(520);
    }
    lookAt(figure.querySelector(".reader__chips"));
    await wait(300);
    chips[3].classList.remove("is-wait");
  }

  const io = new IntersectionObserver(
    ([entry]) => {
      if (!entry.isIntersecting) return;
      io.disconnect();
      read();
    },
    { threshold: 0.5 },
  );
  io.observe(figure);
}
