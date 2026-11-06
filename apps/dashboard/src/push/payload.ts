// What the backend sends in a push message (aivee_api.push.sender.PushMessage) and how the
// service worker turns it into a notification. Shared by sw.ts and the tests.

export interface PushPayload {
  title: string;
  body: string;
  /** Opened when the notification is tapped. */
  url: string;
  /** Same tag replaces the older notification (one per alert). */
  tag: string;
}

export const DEFAULT_TITLE = 'AiVee';
export const DEFAULT_URL = '/alerte';

export function notificationFromPush(data: Partial<PushPayload>): {
  title: string;
  options: NotificationOptions;
} {
  // Only same-origin paths ("//host" would leave the app).
  const url = typeof data.url === 'string' && /^\/(?!\/)/.test(data.url) ? data.url : DEFAULT_URL;
  return {
    title: data.title || DEFAULT_TITLE,
    options: {
      body: data.body ?? '',
      tag: data.tag || 'aivee',
      data: { url },
      icon: '/icons/icon-192.png',
      badge: '/icons/badge-96.png',
      lang: 'ro',
    },
  };
}
