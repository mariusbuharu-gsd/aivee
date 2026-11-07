// Price configurator in "Planuri": reads the three inputs, asks pricing.js for the quote and
// renders the receipt (plan, lines, monthly and yearly total) plus a small picture of the set-up,
// one tile per location with a dot per camera (coral dots are cameras above the plan's included ones).
// The total counts up to its new value unless reduced motion is on. Screen readers get one
// polite summary per change from #calc-live; the counting number itself is aria-hidden.
// Without JS the HTML receipt shows the default set-up.

import { LIMITS, plural, quote } from "./pricing.js";

const form = /** @type {HTMLFormElement | null} */ (document.getElementById("calc-form"));
const out = document.getElementById("calc-out");

if (form && out) {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)");
  const lei = new Intl.NumberFormat("ro-RO");
  const $ = (id) => /** @type {HTMLElement} */ (document.getElementById(id));
  const loc = /** @type {HTMLInputElement} */ ($("calc-loc"));
  const cam = /** @type {HTMLInputElement} */ ($("calc-cam"));
  const els = {
    plan: $("calc-plan"),
    fleet: $("calc-fleet"),
    lines: $("calc-lines"),
    total: $("calc-total"),
    year: $("calc-year"),
    hint: $("calc-hint"),
    live: $("calc-live"),
    sum: $("calc-sum"),
    fleetTxt: $("calc-fleet-txt"),
  };
  const showTotal = (v) => {
    els.total.textContent = lei.format(v);
    els.sum.textContent = lei.format(v);
  };

  let shown = Number(els.total.textContent.replace(/\D/g, "")) || 0;
  let frame = 0;
  let prev = { locations: 0, cameras: 0 };
  let liveTimer = 0;

  const countTo = (target) => {
    cancelAnimationFrame(frame);
    const from = shown;
    if (reduce.matches || from === target) {
      shown = target;
      showTotal(target);
      return;
    }
    const t0 = performance.now();
    const dur = 520;
    const tick = (now) => {
      const t = Math.min(1, (now - t0) / dur);
      const e = 1 - Math.pow(1 - t, 4);
      shown = Math.round(from + (target - from) * e);
      showTotal(shown);
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    out.classList.remove("is-bump");
    void out.offsetWidth;
    out.classList.add("is-bump");
  };

  /** One tile per location, one dot per camera; only dots that did not exist before animate in. */
  const drawFleet = (q, included) => {
    const frag = document.createDocumentFragment();
    for (let l = 0; l < q.locations; l++) {
      const tile = document.createElement("span");
      tile.className = "fleet__loc";
      if (q.mode !== "cloud") tile.classList.add("is-edge");
      if (l >= prev.locations) tile.classList.add("is-new");
      for (let c = 0; c < q.cameras; c++) {
        const dot = document.createElement("i");
        if (c >= included) dot.className = "x";
        if (l < prev.locations && c >= prev.cameras) dot.classList.add("is-new");
        tile.append(dot);
      }
      frag.append(tile);
    }
    els.fleet.replaceChildren(frag);
    els.fleet.dataset.size = q.locations > 6 ? "s" : "m";
    const all = q.locations * q.cameras;
    const extra = q.locations * Math.max(0, q.cameras - included);
    els.fleetTxt.textContent = `${plural(q.locations, "locație", "locații")} · ${plural(all, "cameră", "camere")}${
      q.mode === "cloud" ? "" : " · edge"
    }`;
    els.fleet.parentElement?.querySelector(".fleet__key--x")?.toggleAttribute("hidden", extra === 0);
  };

  const render = (announce) => {
    const q = quote({
      locations: loc.value,
      cameras: cam.value,
      mode: /** @type {RadioNodeList} */ (form.elements.namedItem("mode")).value,
    });
    const planName = q.plan === "pro" ? "Pro" : "Standard";
    els.plan.textContent = planName;
    els.plan.classList.toggle("is-pro", q.plan === "pro");

    els.lines.replaceChildren(
      ...q.lines.map((line) => {
        const row = document.createElement("div");
        const dt = document.createElement("dt");
        const small = document.createElement("small");
        const dd = document.createElement("dd");
        dt.textContent = line.label;
        small.textContent = line.detail;
        dt.append(small);
        dd.className = "num";
        dd.textContent = `${lei.format(line.amount)} lei`;
        row.append(dt, dd);
        return row;
      }),
    );

    drawFleet(q, q.plan === "pro" ? 10 : 4);
    prev = { locations: q.locations, cameras: q.cameras };
    countTo(q.monthly);
    els.year.textContent = lei.format(q.yearly);
    els.hint.textContent = q.hint;
    els.hint.hidden = !q.hint;

    if (announce) {
      // Debounced, so holding a stepper button does not read out every step.
      clearTimeout(liveTimer);
      liveTimer = window.setTimeout(() => {
        els.live.textContent = `Plan recomandat: ${planName}. Total ${lei.format(q.monthly)} lei pe lună, ${lei.format(q.yearly)} lei pe an.${q.hint ? ` ${q.hint}` : ""}`;
      }, 400);
    }
  };

  const limits = { locations: LIMITS.locations, cameras: LIMITS.cameras };
  const syncButtons = () => {
    for (const btn of form.querySelectorAll(".stepper__btn")) {
      const input = /** @type {HTMLInputElement} */ ($(btn.getAttribute("aria-controls")));
      const [min, max] = limits[input.name];
      const v = Number(input.value);
      btn.toggleAttribute("disabled", Number(btn.dataset.step) < 0 ? v <= min : v >= max);
    }
  };

  form.addEventListener("click", (e) => {
    const btn = /** @type {HTMLElement} */ (e.target).closest?.(".stepper__btn");
    if (!btn) return;
    const input = /** @type {HTMLInputElement} */ ($(btn.getAttribute("aria-controls")));
    const [min, max] = limits[input.name];
    input.value = String(Math.min(max, Math.max(min, (Number(input.value) || min) + Number(btn.dataset.step))));
    syncButtons();
    render(true);
    // A disabled button loses focus; keep the keyboard user on the field instead.
    if (btn.hasAttribute("disabled")) input.focus();
  });

  form.addEventListener("input", (e) => {
    const input = /** @type {HTMLInputElement} */ (e.target);
    if (input.type === "number" && input.value === "") return; // let the visitor finish typing
    syncButtons();
    render(true);
  });

  // Typed values outside the range snap back when the field is left.
  form.addEventListener("change", (e) => {
    const input = /** @type {HTMLInputElement} */ (e.target);
    if (input.type !== "number") return;
    const [min, max] = limits[input.name];
    const n = Math.round(Number(input.value));
    input.value = String(Number.isFinite(n) && input.value !== "" ? Math.min(max, Math.max(min, n)) : min);
    syncButtons();
    render(true);
  });

  form.addEventListener("submit", (e) => e.preventDefault());

  syncButtons();
  render(false);
}
