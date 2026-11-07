const URL_RE = /^([a-z][a-z0-9+.-]*):\/\/([^/?#]*)(.*)$/i;
const DEFAULT_PORTS: Record<string, string> = { rtsp: '554', http: '80', https: '443' };

/**
 * A camera source as the devices list shows it: no user or password, no default port and the
 * path (with any query, which can carry credentials too) shortened to "/…". Sources that are not
 * URLs (a device index, a file path) come back as they are. The full value appears only when
 * the camera is edited.
 */
export function maskSource(source: string): string {
  const s = source.trim();
  const m = URL_RE.exec(s);
  if (!m) return s;
  const [, scheme = '', authority = '', rest = ''] = m;
  const at = authority.lastIndexOf('@');
  const user = at >= 0 ? '••••@' : '';
  let host = at >= 0 ? authority.slice(at + 1) : authority;
  const port = DEFAULT_PORTS[scheme.toLowerCase()];
  if (port && host.endsWith(`:${port}`)) host = host.slice(0, -port.length - 1);
  const tail = rest && rest !== '/' ? '/…' : '';
  return `${scheme}://${user}${host}${tail}`;
}
