// Example requests for the rule composer, per location type (`restaurant`, `terrace`, `event`,
// `shop`, `other` in the API). Picking one only fills the text; the usual translate → "Ce am
// înțeles" → confirm flow still decides what is saved.

const RESTAURANT = [
  'Anunță-mă dacă la o masă nu vine nimeni de 2 minute',
  'Anunță-mă dacă un client ridică mâna',
  'Anunță-mă dacă o masă rămâne nedebarasată 3 minute după ce pleacă clienții',
  'Anunță-mă dacă dispare un pahar de pe masă',
];

const SHOP = [
  'Anunță-mă dacă la intrare sunt cel puțin 4 persoane și nu e nimeni de la personal',
  'Anunță-mă dacă un client ridică mâna',
  'Anunță-mă dacă la intrare așteaptă cineva de 2 minute și nu vine nimeni',
];

const EVENT = [
  'Anunță-mă dacă la intrare sunt cel puțin 6 persoane la coadă',
  'Anunță-mă dacă un invitat ridică mâna',
  'Anunță-mă dacă la o masă nu vine nimeni de 3 minute',
  'Anunță-mă dacă o masă rămâne nedebarasată 5 minute după ce pleacă invitații',
];

const OTHER = [
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

/** 3–4 example requests for the location type; unknown types get the general set. */
export function ruleTemplates(type: string | null | undefined): string[] {
  return BY_TYPE[type ?? ''] ?? OTHER;
}
