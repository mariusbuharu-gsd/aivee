// Example requests for the rule composer, per location type (`restaurant`, `terrace`, `event`,
// `shop`, `other` in the API). Picking one only fills the text; the usual translate → "Ce am
// înțeles" → confirm flow still decides what is saved.

/**
 * Open rules first: they show that any thing the camera can see works, not only our presets.
 * Both are drafted by the translator (`object_present` / `visual`) and by the mock.
 */
const OPEN = ['Anunță-mă dacă apare un urs', 'Anunță-mă dacă e foc'];

const RESTAURANT = [
  ...OPEN,
  'Anunță-mă dacă la o masă nu vine nimeni de 2 minute',
  'Anunță-mă dacă un client ridică mâna',
  // object_gone: edge, translator (prompt rule 5) and AI verification all support it.
  'Anunță-mă dacă dispare un pahar de pe masă',
];

const SHOP = [
  ...OPEN,
  'Anunță-mă dacă la intrare sunt cel puțin 4 persoane și nu e nimeni de la personal',
  'Anunță-mă dacă un client ridică mâna',
  'Anunță-mă dacă la intrare așteaptă cineva de 2 minute și nu vine nimeni',
];

const EVENT = [
  ...OPEN,
  'Anunță-mă dacă la intrare sunt cel puțin 6 persoane la coadă',
  'Anunță-mă dacă un invitat ridică mâna',
  'Anunță-mă dacă la o masă nu vine nimeni de 3 minute',
];

const OTHER = [
  ...OPEN,
  'Anunță-mă dacă la intrare sunt cel puțin 3 persoane și nu e nimeni de la personal',
  'Anunță-mă dacă un client ridică mâna',
  'Anunță-mă dacă la o masă nu vine nimeni de 2 minute',
];

const BY_TYPE: Record<string, string[]> = {
  restaurant: RESTAURANT,
  terrace: RESTAURANT,
  shop: SHOP,
  event: EVENT,
  other: OTHER,
};

/** The two open examples, then 3 for the location type; unknown types get the general set. */
export function ruleTemplates(type: string | null | undefined): string[] {
  return BY_TYPE[type ?? ''] ?? OTHER;
}
