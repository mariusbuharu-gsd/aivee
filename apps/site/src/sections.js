// Section scenes (Cum, Scenarii, Pentru echipa ta, Impact, Arhitectură): every [data-play] block
// plays its CSS timeline when it is half in view and rewinds once it is fully out of view, so it
// plays again on the way back. Numbers marked [data-count] count up alongside.
// The HTML is the finished state. Only html.motion arms the blocks (class "armed"), so without JS,
// with reduced motion or if this module fails, every scene simply shows its last frame.

const root = document.documentElement;

if (root.classList.contains("motion") && "IntersectionObserver" in window) {
  const formats = {
    int: (v) => String(Math.round(v)),
    dec1: (v) => v.toFixed(1).replace(".", ","),
    mmss: (v) => {
      const s = Math.round(v);
      return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
    },
  };
  const ease = (t) => 1 - Math.pow(1 - t, 3);

  // A block taller than most of the screen (cards stacked on a phone) plays part by part, each
  // part when it scrolls in, with the stagger delays zeroed by the "solo" class.
  const units = [];
  for (const block of document.querySelectorAll("[data-play]")) {
    if (block.offsetHeight > innerHeight * 0.75 && block.children.length > 1) {
      block.classList.add("solo");
      units.push(...block.children);
    } else units.push(block);
  }

  for (const unit of units) {
    const counters = [...unit.querySelectorAll("[data-count]")].map((el) => ({
      el,
      fmt: formats[el.dataset.count] ?? formats.int,
      from: Number(el.dataset.from ?? 0),
      to: Number(el.dataset.to),
      // data-delay is relative to the scene; the scene's own stagger (--b, zeroed in solo mode)
      // is added so the numbers stay in step with the CSS.
      delay: Number(el.dataset.delay ?? 0) + (parseFloat(getComputedStyle(el).getPropertyValue("--b")) || 0) * 1000,
      dur: Number(el.dataset.dur ?? 1000),
    }));
    let run = 0;
    let playing = false;

    // Armed and not playing, every animation sits paused on its first frame (styles.css).
    // Re-arming restarts them from zero.
    const rewind = () => {
      run++;
      playing = false;
      unit.classList.remove("is-play", "armed");
      void unit.offsetWidth;
      unit.classList.add("armed");
      for (const c of counters) c.el.textContent = c.fmt(c.from);
    };

    const play = () => {
      const id = ++run;
      playing = true;
      unit.classList.add("is-play");
      const t0 = performance.now();
      const tick = (now) => {
        if (id !== run) return;
        let busy = false;
        for (const c of counters) {
          const t = Math.min(1, Math.max(0, (now - t0 - c.delay) / c.dur));
          if (t < 1) busy = true;
          c.el.textContent = c.fmt(c.from + (c.to - c.from) * ease(t));
        }
        if (busy) requestAnimationFrame(tick);
      };
      if (counters.length) requestAnimationFrame(tick);
    };

    rewind();
    // Plays once its top is in the upper three quarters of the screen (or it fills it)...
    new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !playing) play();
      },
      { rootMargin: "0px 0px -25% 0px" },
    ).observe(unit);
    // ...and rewinds only when it is fully out of view, so the reset is never seen.
    new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting && playing) rewind();
    }).observe(unit);
  }
}
