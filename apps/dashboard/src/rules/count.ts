/**
 * A Romanian count: "1 alertă", "12 alerte", "21 de alerte", "nicio alertă". "de" comes after
 * numbers from 20 whose last two digits are 00 or 20–99.
 */
export function countRo(n: number, one: string, many: string, none: string): string {
  if (n === 0) return none;
  if (n === 1) return `1 ${one}`;
  const r = n % 100;
  return n >= 20 && (r === 0 || r >= 20) ? `${n} de ${many}` : `${n} ${many}`;
}

export const alertsCount = (n: number) => countRo(n, 'alertă', 'alerte', 'nicio alertă');
export const camerasCount = (n: number) => countRo(n, 'cameră', 'camere', 'nicio cameră');
