// Copy buttons in the pilot section: each <button data-copy="<id>"> copies the text of the element
// with that id. Progressive enhancement: the phone and e-mail stay selectable text without JS.

const status = document.querySelector(".contact__status");

async function copy(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  // Fallback for browsers without the async clipboard API (or a non-secure context).
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.append(area);
  area.select();
  const ok = document.execCommand("copy");
  area.remove();
  if (!ok) throw new Error("copy failed");
}

for (const button of document.querySelectorAll("[data-copy]")) {
  button.addEventListener("click", async () => {
    const target = document.getElementById(button.dataset.copy ?? "");
    if (!target) return;
    const label = button.closest(".contact__row")?.querySelector("dt")?.textContent ?? "Textul";
    try {
      await copy(target.textContent.trim());
      if (status) status.textContent = `${label} a fost copiat.`;
    } catch {
      if (status) status.textContent = "Nu am putut copia. Selectează textul și copiază-l manual.";
    }
  });
}
