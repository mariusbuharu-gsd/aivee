// The scroll story: the hero dives into the right pupil and opens the room, then one evening
// replays in the scene as the five beats scroll past, and the rule types itself in "Cum funcționează".
//
// Runs only when motion is welcome (html.motion, set in <head>). It loads the self-hosted GSAP,
// ScrollTrigger and Lenis on demand, so reduced-motion visitors download none of it and keep a
// still, fully readable page: no smooth scrolling, no pinning. If a script fails to load, the
// `motion` class is removed and the page falls back to the same still layout.

const root = document.documentElement;

function load(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = src;
    s.onload = resolve;
    s.onerror = () => reject(new Error(`failed to load ${src}`));
    document.head.append(s);
  });
}

const $ = (sel, scope = document) => scope.querySelector(sel);
const $$ = (sel, scope = document) => [...scope.querySelectorAll(sel)];
const pad = (n) => String(n).padStart(2, "0");

function smoothScroll(gsap, ScrollTrigger) {
  if (!window.Lenis) return null;
  const lenis = new window.Lenis({ lerp: 0.1 });
  window.__lenis = lenis;
  lenis.on("scroll", ScrollTrigger.update);
  gsap.ticker.add((t) => lenis.raf(t * 1000));
  gsap.ticker.lagSmoothing(0);
  return lenis;
}

/** Hero: the eyes grow from the right pupil while the room opens as a circle from the same point. */
function dive(gsap, ScrollTrigger) {
  const hero = $(".dive");
  const eyes = $(".eyes", hero);
  const room = $(".room", hero);
  const pupil = $(".eye-r .pupil", hero);
  if (!hero || !eyes || !room || !pupil) return;
  const wide = matchMedia("(min-width: 861px)").matches;
  const scene = $(".cam", room);
  const z4 = $(".z4", scene);
  const z4Label = $(".z4-label", scene);
  z4.classList.remove("is-alert");
  z4Label.textContent = "MASA 4 · 0:00";
  $(".hud--r", scene).textContent = "21:40:00";

  let cx = 63;
  let cy = 40;
  const origin = () => {
    gsap.set(eyes, { scale: 1 });
    const h = hero.getBoundingClientRect();
    const p = pupil.getBoundingClientRect();
    const e = eyes.getBoundingClientRect();
    cx = ((p.left + p.width / 2 - h.left) / h.width) * 100;
    cy = ((p.top + p.height / 2 - h.top) / h.height) * 100;
    hero.style.setProperty("--cx", `${cx}%`);
    hero.style.setProperty("--cy", `${cy}%`);
    return `${((p.left + p.width / 2 - e.left) / e.width) * 100}% ${((p.top + p.height / 2 - e.top) / e.height) * 100}%`;
  };
  gsap.set(eyes, { transformOrigin: origin() });

  const tl = gsap.timeline({ defaults: { ease: "none" } });
  tl.to(".dive__copy", { opacity: 0, y: -40, duration: 0.25 }, 0)
    .to(eyes, { scale: wide ? 14 : 10, duration: 0.6, ease: "power2.in" }, 0.05)
    .fromTo(
      room,
      { clipPath: () => `circle(0% at ${cx}% ${cy}%)` },
      { clipPath: "circle(85% at 50% 50%)", duration: 0.45, ease: "power2.out" },
      0.45,
    )
    // The eyes are gone before the room is wide open, so no half circle sits behind the card.
    .to(eyes, { opacity: 0, duration: 0.1 }, 0.52)
    .from($$(".det", room), { scale: 1.25, opacity: 0, duration: 0.2, stagger: 0.04 }, 0.75)
    .from($(".room__cap", room), { opacity: 0, y: 12, duration: 0.15 }, 0.9);

  ScrollTrigger.create({
    trigger: hero,
    start: "top top",
    end: wide ? "+=170%" : "+=120%",
    pin: true,
    scrub: 0.5,
    animation: tl,
    invalidateOnRefresh: true,
    onUpdate: (s) => {
      eyes.toggleAttribute("data-eyes-frozen", s.progress > 0.005);
      const alert = s.progress > 0.85;
      z4.classList.toggle("is-alert", alert);
      z4Label.textContent = alert ? "MASA 4 · 6:00 FĂRĂ OSPĂTAR" : "MASA 4 · 0:00";
      $(".hud--r", scene).textContent = alert ? "21:46:00" : "21:40:00";
    },
  });
  ScrollTrigger.addEventListener("refreshInit", () => gsap.set(eyes, { transformOrigin: origin() }));
}

/** Story: one timeline scrubbed by the five beats. */
function evening(gsap, ScrollTrigger) {
  const scene = $(".story .cam");
  const beats = $(".beats");
  if (!scene || !beats) return;
  const z4 = $(".z4", scene);
  const z4Label = $(".z4-label", scene);
  const clock = $(".clock", scene);
  const note = $(".story .note");
  const noteTitle = $(".note__title", note);
  const staff = $(".staff", scene);
  gsap.set($$(".g", scene), { opacity: 0, scale: 0.92, transformOrigin: "50% 100%" });
  gsap.set(note, { yPercent: 140, opacity: 0, rotate: 4 });
  z4.classList.remove("is-alert");

  const tl = gsap.timeline({ defaults: { ease: "none" } });
  tl.to($$(".person.g", scene), { opacity: 1, scale: 1, duration: 0.6, stagger: 0.2 }, 0.1)
    .to($$(".det.g", scene), { opacity: 1, scale: 1, duration: 0.4, stagger: 0.2 }, 0.4)
    .to(staff, { xPercent: -170, duration: 0.6, ease: "sine.inOut" }, 1.1)
    .to(staff, { xPercent: 0, duration: 0.6, ease: "sine.inOut" }, 1.75)
    .to({}, { duration: 1 }, 2.4)
    .to(note, { yPercent: 0, opacity: 1, rotate: -2, duration: 0.5, ease: "back.out(1.4)" }, 3.2)
    .to(staff, { xPercent: 190, duration: 0.8, ease: "sine.inOut" }, 4.1)
    .to(note, { rotate: 0, duration: 0.3 }, 4.1);
  const total = tl.duration();

  ScrollTrigger.create({
    trigger: beats,
    start: "top 60%",
    end: "bottom 70%",
    scrub: 0.6,
    animation: tl,
    onUpdate: (self) => {
      const t = self.progress * total;
      // Evening clock 21:40 → 21:47; the table timer runs 0:00 → 6:12 while nobody comes.
      const minutes = Math.min(7, (t / total) * 7.4);
      clock.textContent = `21:${pad(40 + Math.floor(minutes))}:${pad(Math.floor((minutes % 1) * 60))}`;
      const waited = gsap.utils.clamp(0, 372, gsap.utils.mapRange(1.2, 3.0, 0, 372, t));
      const alert = t > 2.6 && t < 4.6;
      z4.classList.toggle("is-alert", alert);
      z4Label.textContent =
        t >= 4.6
          ? "MASA 4 · REZOLVATĂ ÎN 58 s"
          : `MASA 4 · ${Math.floor(waited / 60)}:${pad(Math.floor(waited % 60))}${alert ? " FĂRĂ OSPĂTAR" : ""}`;
      noteTitle.textContent = t >= 4.6 ? "Masa 4 a fost preluată." : "Masa 4 așteaptă de 6 minute.";
    },
  });
}

/** "Cum funcționează": the request types itself once, when the console comes into view. */
function typing(gsap, ScrollTrigger) {
  const ask = $(".ask-text");
  if (!ask) return;
  const full = ask.textContent;
  const state = { n: 0 };
  ScrollTrigger.create({
    trigger: ".console",
    start: "top 75%",
    once: true,
    onEnter: () => {
      ask.textContent = "";
      gsap.to(state, {
        n: full.length,
        duration: 2.2,
        ease: "none",
        onUpdate: () => (ask.textContent = full.slice(0, Math.round(state.n))),
      });
      gsap.from(".console__rule", { opacity: 0, y: 12, duration: 0.5, delay: 2.3 });
    },
  });
}

async function start() {
  try {
    await load("vendor/gsap.min.js");
    await load("vendor/ScrollTrigger.min.js");
    await load("vendor/lenis.min.js").catch(() => undefined); // smooth scroll is optional
  } catch {
    root.classList.remove("motion");
    return;
  }
  const { gsap, ScrollTrigger } = window;
  gsap.registerPlugin(ScrollTrigger);
  smoothScroll(gsap, ScrollTrigger);
  dive(gsap, ScrollTrigger);
  evening(gsap, ScrollTrigger);
  typing(gsap, ScrollTrigger);
  await document.fonts?.ready;
  ScrollTrigger.refresh();
}

if (root.classList.contains("motion")) start();
