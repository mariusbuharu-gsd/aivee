// "Confidențialitate": the "Ce nu păstrăm" eyes open, look at the list, then shut while each
// line is struck out in turn. It plays again each time the column scrolls back into view.
// The HTML already shows the finished state (eyes shut, all struck), so without JS or with
// reduced motion (no html.motion) nothing moves and nothing is missing.

const root = document.documentElement;
const col = document.querySelector(".ledger__col--no");

if (col && root.classList.contains("motion")) {
  const items = [...col.querySelectorAll("li")];
  const wait = (ms) => new Promise((done) => setTimeout(done, ms));
  let run = 0;

  /** Eyes open, nothing struck: the state the animation starts from. */
  function rewind() {
    run++;
    col.classList.remove("is-shut");
    items.forEach((li) => li.classList.add("is-open"));
  }

  async function close() {
    const id = ++run;
    await wait(700);
    if (id !== run) return;
    col.classList.add("is-shut");
    await wait(300);
    for (const li of items) {
      if (id !== run) return;
      li.classList.remove("is-open");
      await wait(380);
    }
  }

  // Rewinds only once the column is fully out of view, so the reset is never seen.
  rewind();
  let playing = false;
  const io = new IntersectionObserver(
    ([entry]) => {
      if (entry.intersectionRatio >= 0.5 && !playing) {
        playing = true;
        close();
      } else if (!entry.isIntersecting && playing) {
        playing = false;
        rewind();
      }
    },
    { threshold: [0, 0.5] },
  );
  io.observe(col);
}
