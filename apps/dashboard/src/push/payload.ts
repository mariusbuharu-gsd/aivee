// What the backend sends in a push message (aivee_api.push.sender.PushMessage) and how the
// service worker turns it into a notification. Shared by sw.ts and the tests.

/** aivee_api.push.sender.PushKind: what the push is about. */
export type PushKind = 'alert' | 'ack' | 'arrived' | 'realert' | 'device' | 'test';

/** Kinds that must ring even when they replace a notification with the same tag. */
const RINGING: ReadonlySet<PushKind> = new Set<PushKind>(['alert', 'realert']);

export interface PushPayload {
  title: string;
  body: string;
  /** Opened when the notification is tapped. */
  url: string;
  /** Same tag replaces the older notification (one per alert). */
  tag: string;
  /** Decides whether a replacement rings. Optional only for pushes from older backends. */
  kind?: PushKind;
}

// Fallback for payloads without `kind` (pushes queued before the backend sent it): ingest's
// `realert.REALERT_TITLE`. Can be removed after the freeze, with the title check below.
const LEGACY_REALERT_TITLE = 'AiVee · Nu a ajuns nimeni';

/** A replaced notification is silent by default: right for the ack, wrong for an alert. */
export function shouldRenotify(data: Partial<PushPayload>): boolean {
  if (data.kind) return RINGING.has(data.kind);
  return data.title === LEGACY_REALERT_TITLE; // legacy fallback, remove after the freeze
}

/** `renotify` is still missing from TypeScript's DOM types; browsers that ignore it stay silent. */
type Options = NotificationOptions & { renotify?: boolean };

export const DEFAULT_TITLE = 'AiVee';
export const DEFAULT_URL = '/alerte';

export function notificationFromPush(data: Partial<PushPayload>): {
  title: string;
  options: Options;
} {
  const renotify = shouldRenotify(data);
  // Only same-origin paths ("//host" would leave the app).
  const url = typeof data.url === 'string' && /^\/(?!\/)/.test(data.url) ? data.url : DEFAULT_URL;
  return {
    title: data.title || DEFAULT_TITLE,
    options: {
      body: data.body ?? '',
      tag: data.tag || 'aivee',
      renotify,
      data: { url },
      icon: '/icons/icon-192.png',
      badge: '/icons/badge-96.png',
      lang: 'ro',
    },
  };
}
