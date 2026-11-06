// Inline SVG icons (stroke-based, 24px grid). Decorative by default; pass `label` to expose one.
const PATHS = {
  live: 'M3 7h13v10H3zM16 10l5-3v10l-5-3',
  rules: 'M4 6h16M4 12h10M4 18h7M17 15l2 2 4-4',
  alerts: 'M6 16V11a6 6 0 0 1 12 0v5l2 2H4zM10 21h4',
  devices: 'M4 5h16v10H4zM9 19h6M12 15v4',
  metrics: 'M4 20V10M10 20V4M16 20v-7M22 20H2',
  mic: 'M12 3a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3zM5 11a7 7 0 0 0 14 0M12 18v3',
  check: 'M5 12l5 5L20 7',
  x: 'M6 6l12 12M18 6L6 18',
  upload: 'M12 16V4M7 9l5-5 5 5M4 20h16',
  edit: 'M4 20h4L19 9l-4-4L4 16zM14 6l4 4',
  trash: 'M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13',
  zones: 'M4 5l7 2 9-2v14l-9 2-7-2zM11 7v14',
  undo: 'M9 14L4 9l5-5M4 9h11a5 5 0 0 1 0 10h-3',
  close: 'M5 19l3-11 8-3 3 11-8 3zM5 19l14-3',
  offline:
    'M3 3l18 18M8.5 8.5A5 5 0 0 0 7 12M16.7 16.7A5 5 0 0 0 17 12M5 5a9 9 0 0 0 0 14M19 19a9 9 0 0 0 0-14',
  snapshot: 'M3 7h4l2-3h6l2 3h4v12H3zM12 17a4 4 0 1 0 0-8 4 4 0 0 0 0 8z',
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({
  name,
  label,
  size = 20,
}: {
  name: IconName;
  label?: string;
  size?: number;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={label ? undefined : true}
      role={label ? 'img' : undefined}
      aria-label={label}
      focusable="false"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}

export function Logo() {
  return (
    <span className="logo">
      {/* The brand mark from docs/brand/aivee-mark-white.svg: two eyes, coral pupils. */}
      <svg width="40" height="22" viewBox="4.5 25.5 91 49" aria-hidden="true" focusable="false">
        <circle cx="29" cy="50" r="19" fill="none" stroke="currentColor" strokeWidth="7" />
        <circle cx="32.6" cy="51.8" r="8" fill="var(--coral)" />
        <circle cx="71" cy="50" r="19" fill="none" stroke="currentColor" strokeWidth="7" />
        <circle cx="74.6" cy="51.8" r="8" fill="var(--coral)" />
      </svg>
      <span className="logo-word">aivee</span>
    </span>
  );
}
