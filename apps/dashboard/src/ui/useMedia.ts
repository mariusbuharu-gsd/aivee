import { useSyncExternalStore } from 'react';

/** True while the media query matches; false where matchMedia is missing (tests). */
export function useMedia(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      if (typeof window.matchMedia !== 'function') return () => undefined;
      const mq = window.matchMedia(query);
      mq.addEventListener('change', onChange);
      return () => mq.removeEventListener('change', onChange);
    },
    () => typeof window.matchMedia === 'function' && window.matchMedia(query).matches,
    () => false,
  );
}

export const PHONE = '(max-width: 760px)';
