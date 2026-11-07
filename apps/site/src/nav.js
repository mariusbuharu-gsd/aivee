// Top nav: always fixed and visible (story.js hides it only during the eyes → story dive), solid
// once the hero is behind; highlights the current chapter, shows reading progress and opens the menu on narrow screens.
// Anchor clicks scroll through Lenis when story.js started it, otherwise natively.

const nav = document.querySelector(".snav");
if (nav) {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const bar = nav.querySelector(".snav__bar");
  const links = [...nav.querySelectorAll(".snav__links a")];
  const menu = nav.querySelector(".snav__menu");
  const onScroll = () => {
    const y = scrollY;
    const max = document.documentElement.scrollHeight - innerHeight;
    if (bar) bar.style.transform = `scaleX(${max > 0 ? Math.min(1, y / max) : 0})`;
    nav.classList.toggle("is-solid", y > innerHeight * 0.6);
  };
  addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  const close = () => {
    nav.classList.remove("is-open");
    menu?.setAttribute("aria-expanded", "false");
    if (menu) menu.textContent = "Meniu";
  };
  menu?.addEventListener("click", () => {
    const open = nav.classList.toggle("is-open");
    menu.setAttribute("aria-expanded", String(open));
    menu.textContent = open ? "Închide" : "Meniu";
  });
  addEventListener("keydown", (e) => {
    if (e.key === "Escape" && nav.classList.contains("is-open")) {
      close();
      menu?.focus();
    }
  });

  document.addEventListener("click", (e) => {
    const a = /** @type {HTMLElement} */ (e.target).closest?.('a[href^="#"]');
    if (!a) return;
    if (nav.contains(a)) close();
    const id = a.getAttribute("href");
    const el = id && id.length > 1 ? document.querySelector(id) : null;
    if (!el) return;
    e.preventDefault();
    const offset = el.id === "top" ? 0 : -(nav.offsetHeight + 16);
    if (window.__lenis) window.__lenis.scrollTo(el, { offset });
    else scrollTo({ top: el.getBoundingClientRect().top + scrollY + offset, behavior: reduce ? "auto" : "smooth" });
    history.replaceState(null, "", id);
    if (el.id === "continut" || a.classList.contains("skip")) el.focus?.();
  });

  // Current chapter: the section crossing the middle of the screen.
  const targets = links.map((a) => document.querySelector(a.getAttribute("href"))).filter(Boolean);
  const io = new IntersectionObserver(
    (entries) => {
      for (const en of entries) {
        if (!en.isIntersecting) continue;
        const id = `#${en.target.id}`;
        for (const a of links) a.setAttribute("aria-current", String(a.getAttribute("href") === id));
      }
    },
    { rootMargin: "-45% 0px -50% 0px" },
  );
  for (const t of targets) io.observe(t);
}
