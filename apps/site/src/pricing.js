// Launch prices for the configurator in the "Planuri" section: lei per month, excluding VAT.
// Pure: no DOM, so `node --test` can check it (test/pricing.test.mjs) and planuri.js renders it.

export const PRICES = {
  standard: { base: 249, cameras: 4 },
  pro: { base: 549, cameras: 10 },
  extraCamera: 49,
  edge: { cloud: 0, "edge-box": 99, "edge-pc": 49 },
};

export const LIMITS = { locations: [1, 20], cameras: [1, 16] };

export const MODES = {
  cloud: "Cloud (standard)",
  "edge-box": "Edge pe cutia noastră",
  "edge-pc": "Edge pe PC-ul tău",
};

const clamp = (value, [min, max]) => {
  const n = Math.round(Number(value));
  return Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : min;
};

/** Romanian count: "1 locație", "3 locații", "20 de locații" ("de" when the last two digits are 00 or 20–99). */
export const plural = (n, one, many) => {
  if (n === 1) return `${n} ${one}`;
  const r = n % 100;
  return `${n} ${r === 0 || r >= 20 ? "de " : ""}${many}`;
};

/**
 * Monthly price for a set-up.
 * One location is on Standard (4 cameras included); two or more are on Pro per location
 * (10 cameras included each). Extra cameras cost 49 each; edge adds a fee per location.
 * @param {{locations: number, cameras: number, mode: string}} input cameras are per location
 * @returns {{plan: "standard" | "pro", locations: number, cameras: number, mode: string,
 *   lines: {label: string, detail: string, amount: number}[], monthly: number, yearly: number, hint: string}}
 */
export function quote({ locations, cameras, mode }) {
  const l = clamp(locations, LIMITS.locations);
  const c = clamp(cameras, LIMITS.cameras);
  const m = mode in PRICES.edge ? mode : "cloud";
  const plan = l === 1 ? "standard" : "pro";
  const { base, cameras: included } = PRICES[plan];
  const lines = [];

  lines.push({
    label: plan === "standard" ? "Standard" : "Pro",
    detail: `${plural(l, "locație", "locații")} × ${base} lei · ${included} camere incluse`,
    amount: base * l,
  });

  const extra = Math.max(0, c - included);
  if (extra > 0) {
    lines.push({
      label: plural(extra * l, "cameră în plus", "camere în plus"),
      detail: l === 1 ? `${extra} × ${PRICES.extraCamera} lei` : `${extra} × ${plural(l, "locație", "locații")} × ${PRICES.extraCamera} lei`,
      amount: extra * l * PRICES.extraCamera,
    });
  }

  if (PRICES.edge[m] > 0) {
    lines.push({
      label: MODES[m],
      detail: `${plural(l, "locație", "locații")} × ${PRICES.edge[m]} lei${m === "edge-box" ? " · contract 12 luni" : ""}`,
      amount: PRICES.edge[m] * l,
    });
  }

  const monthly = lines.reduce((sum, line) => sum + line.amount, 0);
  const hint =
    plan === "standard" && c > PRICES.pro.cameras
      ? `Peste 10 camere? Uită-te și la Pro: include 10 camere și adaugă notificări push pe telefon. Pentru configurația ta ar fi ${
          PRICES.pro.base + (c - PRICES.pro.cameras) * PRICES.extraCamera + PRICES.edge[m]
        } lei/lună.`
      : "";

  return { plan, locations: l, cameras: c, mode: m, lines, monthly, yearly: monthly * 12, hint };
}
