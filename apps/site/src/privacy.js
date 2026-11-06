// "Confidențialitate": the "Ce nu păstrăm" eyes open, look at the list, then shut while each
// line is struck out in turn. The HTML already shows the finished state (eyes shut, all struck),
// so without JS or with reduced motion nothing moves and nothing is missing.

const root = document.documentElement;
const col = document.querySelector(".ledger__col--no");

if (col && root.classList.contains("motion")) {
  const items = [...col.querySelectorAll("li")];
  const wait = (ms) => new Promise((done) => setTimeout(done, ms));

  // Rewind now: the section starts well below the fold, so the reset is never seen.
  col.classList.remove("is-shut");
  items.forEach((li) => li.classList.add("is-open"));

  async function close() {
    await wait(700);
    col.classList.add("is-shut");
    await wait(300);
    for (const li of items) {
      li.classList.remove("is-open");
      await wait(380);
    }
  }

  const io = new IntersectionObserver(
    ([entry]) => {
      if (!entry.isIntersecting) return;
      io.disconnect();
      close();
    },
    { threshold: 0.5 },
  );
  io.observe(col);
}
