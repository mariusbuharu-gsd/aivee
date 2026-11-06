/**
 * Romanian count + noun: "1 zonă", "3 zone", "20 de zone". Numbers whose last two digits are 0 or
 * 20..99 take "de" (except 0 itself and 1..19).
 */
export function plural(n: number, one: string, many: string): string {
  if (n === 1) return `1 ${one}`;
  const rest = Math.abs(n) % 100;
  const de = n !== 0 && (rest === 0 || rest >= 20);
  return `${n} ${de ? 'de ' : ''}${many}`;
}
