/** "45 s", "2 min 10 s". */
export function duration(s: number): string {
  const v = Math.max(0, Math.round(s));
  return v < 60 ? `${v} s` : `${Math.floor(v / 60)} min ${v % 60} s`;
}
