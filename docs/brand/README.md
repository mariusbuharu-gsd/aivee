# AiVee brand and design system

One palette, three typefaces, one rule for night chrome. Applies to the dashboard (`apps/dashboard`),
the PWA, the presentation site (`apps/site`) and the pitch slides.

**Source of truth:** [`tokens.css`](tokens.css). Apps copy its `:root` block to the top of their
stylesheet and build every rule on the variables. When a token changes, change it here first, then
in each app (`apps/dashboard/src/styles.css`).

## Logo

| File | Use |
|---|---|
| `aivee-logo.svg` | horizontal logo on light ground |
| `aivee-logo-white.svg` | horizontal logo on ink / dark ground |
| `aivee-mark.svg`, `aivee-mark-white.svg` | the two eyes alone (avatars, small spaces, inline in UI) |
| `aivee-app-icon.svg` | PWA icon, Telegram bot avatar |
| `favicon.svg` | browser tab (also in `apps/dashboard/public/`) |

- The wordmark is always lowercase **aivee**, Fredoka SemiBold, outlined in the SVGs. In running text the
  product name is written **AiVee**.
- The pupils are always coral `#FF5C6C`; the rings follow the ground (ink on light, white on dark).
- Keep clear space of one eye-width around the logo. Minimum size: mark 16 px tall, logo 24 px tall.
- Don't recolour the pupils, add effects, or replace the eyes with round letters in the word.

## Colour

Light working surface, night chrome in brand ink, coral only where something needs attention.

| Role | Token | Hex | Rules |
|---|---|---|---|
| Ink | `--ink` | `#14161B` | text, primary buttons, sidebar, footer |
| Coral | `--coral` | `#FF5C6C` | pupils, open alerts, alert CTA, focus on dark. Fills and strokes only: 3.0:1 on white, **never small text on light** |
| Coral as text | `--coral-strong` | `#C8283E` | links, coral labels and icons on light (5.5:1) |
| Coral tints | `--coral-tint` `--coral-wash` `--coral-line` | `#FFE3E6` `#FFF4F5` `#FFC2C9` | open-alert cards and chips; text on them is `--coral-deep` `#9E1B2E` |
| Ground / surface | `--ground` `--surface` | `#F6F7F9` `#FFFFFF` | page / cards |
| Inset, hover | `--surface-2` `--surface-3` | `#F6F7F9` `#EEF0F3` | inputs, rows / pressed, placeholders |
| Lines | `--border` `--border-soft` | `#D5D9DF` `#E2E5EA` | controls / cards and dividers |
| Secondary text | `--muted` `--muted-2` | `#4B515C` `#5A606C` | 8:1 and 6.3:1 on white |
| Night | `--night` `--night-2` `--night-3` | `#14161B` `#1B1D22` `#23262D` | chrome, camera media, raised on night |
| Night text | `--night-text` `--night-muted` | `#F2F3F5` `#A3A9B4` | |
| Live / online | `--live`, `--live-tint`, `--live-deep` | `#1F6F99`, `#E3F3FB`, `#0B4A66` | online status, "live" chips on light |
| On camera media | `--live-on-night` `--guest-on-night` | `#7DD3FC` `#E6E8EC` | staff boxes and staff zones / guest boxes and table zones |
| Danger | `--danger` / `--danger-on-night` | `#C8283E` / `#FF8A96` | offline, errors |

### Meaning of colour (keep it consistent everywhere)

- **Coral = needs attention**: an open alert, the zone that triggered it, the one action that resolves it.
  A screen at rest has almost no coral besides the logo.
- **Light blue = staff and live**: staff detection boxes, staff zones, "LIVE" badges, online.
- **White/grey on media = guests and tables.**
- Status is never colour alone: always a word ("deschisă", "offline", "live") or an icon next to it.

### Night chrome

Sidebar, footer, camera media, snapshots and the staff suggestion card are dark. In CSS, add the class
`on-night` (or use `.sidebar` / `.suggestion`): it remaps `--text`, `--muted`, `--surface*`, `--border*`,
`--danger` and `--focus` to their night values, so the same component rules work on both grounds.
On night, the primary button turns coral with ink text.

## Type

| Role | Family | Weights | Where |
|---|---|---|---|
| Display | Fredoka (`--display`) | 600 | logo, page titles (h1), big numbers on the site |
| UI and body | Figtree (`--sans`) | 400, 500, 600, 700 | everything else |
| Data | JetBrains Mono (`--mono`) | 500, 700 | ids (`cam-01`, `edge-01`), timers, scores, metrics, detection labels |

Google Fonts URL: `https://fonts.googleapis.com/css2?family=Figtree:wght@400;500;600;700&family=Fredoka:wght@600&family=JetBrains+Mono:wght@500;700&display=swap`

Base size 15 px in the dashboard, 17 px on the site. Use `font-variant-numeric: tabular-nums` for metrics
and timers. UI copy is Romanian, with diacritics (ă, â, î, ș, ț).

## Shape and rhythm

- Radius: `--radius-xs` 6 (chips, labels), `--radius-sm` 10 (buttons, inputs, rows), `--radius` 14 (cards,
  tiles), `--radius-lg` 18 (phone sheets, big cards).
- Spacing on a 4 px grid; `--gap` 16 between cards. Lay out groups with flex/grid `gap`, not margins.
- Touch targets ≥ `--tap` 44 px; waiters use the PWA one-handed.
- Shadows only on floating elements (`--shadow-pop`: notifications, toasts). Cards use a 1 px border.

## Components (dashboard names)

| Component | Look |
|---|---|
| `.btn` | white, `--border`, 600 weight; `.btn-primary` ink; `.btn-accent` coral (one per screen, for the alert action); `.btn-ghost`; `.btn-danger` coral-strong text |
| `.input` | `--surface-2` fill, `--border`, focus border ink |
| `.pill` | mono, outlined in `currentColor`: alert coral-strong, live `--live`, off `--danger`, muted |
| `.feed-item.is-open` | coral wash + coral line; closed items plain white |
| `.tile` | white card, dark 16:9 media, LIVE / OFFLINE badge top-left |
| `.det` / `.det-staff` | guest box `--guest-on-night`, staff box `--live-on-night`, mono label |
| `.zone-shape` | table: guest colour, entrance: coral, staff: light blue; selected = thicker stroke |
| `.suggestion` | night card, coral "Confirmă", outlined "Respinge" |
| `.json` | night code block |

## Privacy shows in the design

- Faces are blurred in every snapshot and illustration; never draw a sharp face.
- Staff are identified by role ("angajat", "personal"), never by name in detection labels.
- Staff confirmation is always an explicit question with two buttons: "Pare angajat — confirmi?".

## Voice

Plain Romanian, second person singular, short. Say what happened and where: "Masa 4 așteaptă de 6 min",
not "Eveniment detectat". Buttons say what they do: "Preiau", "Confirmă", "Activează regula".
