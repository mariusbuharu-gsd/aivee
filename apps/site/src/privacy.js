// "Confidențialitate": one camera frame travels camera → analysis → blur → bin, and only the
// alert stays. The Cloud / Edge switch moves the restaurant fence and swaps the promise. The HTML
// shows both promises and the finished route, so without JS nothing is missing; with reduced
// motion the switch still works but nothing travels. No library: timeouts and CSS transitions.

const root = document.documentElement;
const section = document.querySelector(".priv");

if (section && root.classList.contains("js")) {
  const sw = section.querySelector(".priv__switch");
  const buttons = [...sw.querySelectorAll("button")];
  const modes = [...section.querySelectorAll(".priv__mode")];
  const route = section.querySelector(".route");
  const where = section.querySelector(".route__where");
  const frame = section.querySelector(".route__frame");
  const keep = section.querySelector(".keep");
  const icons = [...route.querySelectorAll(".st__ic")];
  const WHERE = { cloud: "în cloud, servere în UE", edge: "pe calculatorul din locație" };
  const wait = (ms) => new Promise((done) => setTimeout(done, ms));
  let run = 0;

  // The frame travels only with motion and while the fence is drawn (wide screens).
  const canTravel = () => root.classList.contains("motion") && getComputedStyle(frame).display !== "none";

  async function travel() {
    const id = ++run;
    if (!canTravel()) return keep.classList.remove("is-wait");
    keep.classList.add("is-wait");
    frame.classList.remove("is-blur");
    const box = route.getBoundingClientRect();
    const x = (i) => {
      const r = icons[i].getBoundingClientRect();
      return r.left - box.left + r.width / 2 - 22;
    };
    frame.style.transition = "none";
    frame.style.opacity = "1";
    frame.style.transform = `translate(${x(0)}px, 17px)`;
    await wait(400);
    for (let i = 1; i < icons.length; i++) {
      if (id !== run) return;
      frame.style.transition = "transform .7s cubic-bezier(.4, .1, .2, 1), opacity .4s";
      frame.style.transform = `translate(${x(i)}px, 17px)`;
      await wait(750);
      if (i === 2) frame.classList.add("is-blur");
    }
    frame.style.opacity = "0";
    frame.style.transform = `translate(${x(3)}px, 30px) scale(.4)`;
    await wait(350);
    if (id === run) keep.classList.remove("is-wait");
  }

  function show(mode) {
    buttons.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === mode)));
    modes.forEach((m) => (m.hidden = m.dataset.mode !== mode));
    route.dataset.mode = mode;
    where.textContent = WHERE[mode];
  }

  sw.hidden = false;
  show("cloud");
  for (const b of buttons) b.addEventListener("click", () => { show(b.dataset.mode); travel(); });

  if (canTravel()) {
    keep.classList.add("is-wait");
    const io = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return;
        io.disconnect();
        travel();
      },
      { threshold: 0.5 },
    );
    io.observe(route);
  }
}
