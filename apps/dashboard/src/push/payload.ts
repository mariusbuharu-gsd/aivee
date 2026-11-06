// What the backend sends in a push message (aivee_api.push.sender.PushMessage) and how the
// service worker turns it into a notification. Shared by sw.ts and the tests.

export interface PushPayload {
  title: string;
  body: string;
  /** Opened when the notification is tapped. */
  url: string;
  /** Same tag replaces the older notification (one per alert). */
  tag: string;
  /** Optional, for when the backend starts sending it; the title is the fallback key. */
  kind?: 'alert' | 'ack' | 'realert';
}

/** ingest `realert.REALERT_TITLE`: nobody arrived after "Merg eu", so the phone must ring. */
export const REALERT_TITLE = 'AiVee · Nu a ajuns nimeni';

/** `renotify` is still missing from TypeScript's DOM types; browsers that ignore it stay silent. */
type Options = NotificationOptions & { renotify?: boolean };

export const DEFAULT_TITLE = 'AiVee';
export const DEFAULT_URL = '/alerte';

export function notificationFromPush(data: Partial<PushPayload>): {
  title: string;
  options: Options;
} {
  // Only same-origin paths ("//host" would leave the app).
  // A replaced notification is silent by default: right for the ack, wrong for the re-alert.
  const renotify = data.kind ? data.kind === 'realert' : data.title === REALERT_TITLE;
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
