// "Cere un demo" in the pilot section. The site has no backend: a valid submit opens the
// visitor's e-mail app (mailto:) addressed to the contact e-mail shown on the page, with the
// subject and body filled in from the fields, then shows a thank-you that says exactly that.
// Without JS the form is not needed: the phone and e-mail next to it stay usable.

const form = /** @type {HTMLFormElement | null} */ (document.getElementById("demo-form"));
const done = document.getElementById("demo-done");
const again = document.getElementById("demo-again");
const to = document.getElementById("contact-email")?.textContent.trim() ?? "";

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
const isPhone = (v) => /^[+\d][\d\s().-]*$/.test(v) && v.replace(/\D/g, "").length >= 9;

/** Field name → Romanian message for an invalid value ("" when valid). */
const rules = {
  name: (v) => (v.length >= 2 ? "" : "Scrie numele, ca să știm cu cine vorbim."),
  place: (v) => (v.length >= 2 ? "" : "Scrie numele restaurantului sau al locației."),
  contact: (v) =>
    !v
      ? "Lasă un email sau un număr de telefon."
      : EMAIL.test(v) || isPhone(v)
        ? ""
        : "Nu pare un email sau un telefon valid. Exemplu: nume@restaurant.ro sau 0722 123 456.",
};

if (form && done) {
  const field = (name) => /** @type {HTMLInputElement} */ (form.elements.namedItem(name));
  const check = (name) => {
    const el = field(name);
    const msg = rules[name](el.value.trim());
    el.setAttribute("aria-invalid", String(Boolean(msg)));
    const out = document.getElementById(`e-${name}`);
    if (out) out.textContent = msg;
    return !msg;
  };

  // Re-check a field the visitor is correcting; never nag before the first submit.
  form.addEventListener("input", (e) => {
    const name = /** @type {HTMLInputElement} */ (e.target).name;
    if (name in rules && field(name).getAttribute("aria-invalid") === "true") check(name);
  });

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const bad = Object.keys(rules).filter((name) => !check(name));
    if (bad.length) {
      field(bad[0]).focus();
      return;
    }
    const value = (name) => field(name)?.value.trim() ?? "";
    const tables = /** @type {RadioNodeList} */ (form.elements.namedItem("tables")).value;
    const lines = [
      `Nume: ${value("name")}`,
      `Restaurant: ${value("place")}`,
      `Contact: ${value("contact")}`,
      value("city") && `Oraș: ${value("city")}`,
      tables && `Număr de mese: ${tables}`,
      value("msg") && `\n${value("msg")}`,
    ].filter(Boolean);
    const subject = `Cerere demo AiVee — ${value("place")}`;
    const href = `mailto:${to}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(lines.join("\n"))}`;
    window.location.href = href;
    form.hidden = true;
    done.hidden = false;
    done.focus();
  });

  again?.addEventListener("click", () => {
    done.hidden = true;
    form.hidden = false;
    field("name").focus();
  });
}
