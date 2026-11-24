// RTSP addresses for "Adaugă cameră → Cameră IP": the owner picks the brand and types the IP,
// user and password; the address is built here. Detection always reads the substream (smaller,
// 10–15 fps): the main 4 MP stream costs CPU and gains nothing for the rules.

export type CameraBrand = 'tapo' | 'hikvision' | 'dahua' | 'reolink' | 'other';

export interface BrandInfo {
  value: CameraBrand;
  label: string;
  /** Path of the substream, after the port; empty for "other" (the owner types it). */
  path: string;
  /** What the camera's own account is called in its app, and where to find it. */
  hint: string;
  /** The usual user name, prefilled. */
  user: string;
}

export const RTSP_PORT = '554';

export const BRANDS: BrandInfo[] = [
  {
    value: 'tapo',
    label: 'Tapo (TP-Link)',
    path: '/stream2',
    user: '',
    hint: 'În aplicația Tapo: camera → Setări → Setări avansate → Cont cameră. Nu e contul TP-Link.',
  },
  {
    value: 'hikvision',
    label: 'Hikvision',
    path: '/Streaming/Channels/102',
    user: 'admin',
    hint: 'Contul din aplicația Hik-Connect sau de pe pagina web a camerei.',
  },
  {
    value: 'dahua',
    label: 'Dahua',
    path: '/cam/realmonitor?channel=1&subtype=1',
    user: 'admin',
    hint: 'Contul din aplicația DMSS sau de pe pagina web a camerei.',
  },
  {
    value: 'reolink',
    label: 'Reolink',
    path: '/h264Preview_01_sub',
    user: 'admin',
    hint: 'Contul din aplicația Reolink. RTSP trebuie pornit: Setări → Rețea → Avansat → Porturi.',
  },
  {
    value: 'other',
    label: 'Altă marcă',
    path: '',
    user: 'admin',
    hint: 'Calea fluxului secundar (substream) e în manualul camerei sau pe pagina ei web.',
  },
];

export const brandInfo = (b: CameraBrand): BrandInfo =>
  BRANDS.find((x) => x.value === b) ?? (BRANDS.at(-1) as BrandInfo);

export interface RtspInput {
  brand: CameraBrand;
  /** IP or hostname, optionally with ":port". */
  host: string;
  user: string;
  password: string;
  /** "other" only: the stream path ("live/sub" or "/live/sub"). */
  path?: string;
  /** "other" only, when `host` has no port. */
  port?: string;
}

/** `rtsp://user:pass@ip:554/<brand substream>`; user and password URL-escaped. */
export function buildRtspUrl({ brand, host, user, password, path, port }: RtspInput): string {
  const h = host.trim();
  const withPort = /:\d+$/.test(h) ? h : `${h}:${port?.trim() || RTSP_PORT}`;
  const info = brandInfo(brand);
  const raw = brand === 'other' ? (path ?? '').trim() : info.path;
  const tail = raw.startsWith('/') ? raw : `/${raw}`;
  const u = user.trim();
  const auth = u ? `${enc(u)}${password ? `:${enc(password)}` : ''}@` : '';
  return `rtsp://${auth}${withPort}${tail}`;
}

const enc = (s: string) => encodeURIComponent(s);

const IPV4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/;
const HOSTNAME =
  /^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$/i;

/** Null when `value` is an IP (or hostname) with an optional port; else what to fix. */
export function checkHost(value: string): string | null {
  const v = value.trim();
  if (!v) return 'Scrie adresa IP a camerei, de exemplu 192.168.1.20.';
  if (v.includes('://') || v.includes('/') || v.includes('@')) {
    return 'Scrie doar adresa IP, de exemplu 192.168.1.20. Restul îl completăm noi.';
  }
  const m = /^(.*?)(?::(\d+))?$/.exec(v);
  const host = m?.[1] ?? '';
  const port = m?.[2];
  if (port !== undefined && (Number(port) < 1 || Number(port) > 65535)) {
    return 'Portul trebuie să fie între 1 și 65535.';
  }
  const ip = IPV4.exec(host);
  if (ip) {
    return ip.slice(1).every((n) => Number(n) <= 255)
      ? null
      : `„${host}” nu e o adresă IP. Arată ca 192.168.1.20.`;
  }
  if (/^[\d.]+$/.test(host) || !HOSTNAME.test(host)) {
    return `„${host}” nu e o adresă IP. Arată ca 192.168.1.20.`;
  }
  return null;
}

const URL_RE = /^([a-z][a-z0-9+.-]*):\/\/([^/?#]*)(.*)$/i;

export interface SourceParts {
  scheme: string;
  /** Decoded; empty when there is none. */
  user: string;
  /** Decoded; empty when there is none. */
  password: string;
  /** Host with its port, as written. */
  host: string;
  /** Path and query, as written. */
  rest: string;
}

/** The parts of a URL source; null for sources that are not URLs (a device index, a file). */
export function parseSourceUrl(source: string): SourceParts | null {
  const m = URL_RE.exec(source.trim());
  if (!m) return null;
  const [, scheme = '', authority = '', rest = ''] = m;
  const at = authority.lastIndexOf('@');
  const creds = at >= 0 ? authority.slice(0, at) : '';
  const colon = creds.indexOf(':');
  const dec = (s: string) => {
    try {
      return decodeURIComponent(s);
    } catch {
      return s;
    }
  };
  return {
    scheme,
    user: dec(colon >= 0 ? creds.slice(0, colon) : creds),
    password: dec(colon >= 0 ? creds.slice(colon + 1) : ''),
    host: at >= 0 ? authority.slice(at + 1) : authority,
    rest,
  };
}

/**
 * The same address with a new host and user; an empty `password` keeps the one it had, so the
 * edit form never needs to show the stored password.
 */
export function replaceCredentials(
  source: string,
  next: { host: string; user: string; password: string },
): string {
  const p = parseSourceUrl(source);
  if (!p) return source;
  const password = next.password || p.password;
  const user = next.user.trim();
  const auth = user ? `${enc(user)}${password ? `:${enc(password)}` : ''}@` : '';
  return `${p.scheme}://${auth}${next.host.trim()}${p.rest}`;
}

/** The address with its password as "••••": what the forms show; user, host and path stay. */
export function maskPassword(source: string): string {
  const m = URL_RE.exec(source.trim());
  if (!m) return source;
  const [, scheme = '', authority = '', rest = ''] = m;
  const at = authority.lastIndexOf('@');
  if (at < 0) return source.trim();
  const creds = authority.slice(0, at);
  const colon = creds.indexOf(':');
  if (colon < 0) return source.trim();
  return `${scheme}://${creds.slice(0, colon)}:••••@${authority.slice(at + 1)}${rest}`;
}

/** Which brand template an address was built from; "other" when none matches. */
export function brandOf(source: string): CameraBrand {
  const p = parseSourceUrl(source);
  if (!p || p.scheme.toLowerCase() !== 'rtsp') return 'other';
  return BRANDS.find((b) => b.path && b.path === p.rest)?.value ?? 'other';
}
