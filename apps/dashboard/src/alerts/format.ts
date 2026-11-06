/** "45 s", "2 min 10 s", "3 min". */
export function duration(s: number): string {
  const v = Math.max(0, Math.round(s));
  if (v < 60) return `${v} s`;
  const min = `${Math.floor(v / 60)} min`;
  return v % 60 ? `${min} ${v % 60} s` : min;
}

/** A position in a clip: "00:12", "01:35". */
export function clock(s: number): string {
  const v = Math.max(0, Math.floor(s));
  const mm = String(Math.floor(v / 60)).padStart(2, '0');
  return `${mm}:${String(v % 60).padStart(2, '0')}`;
}
