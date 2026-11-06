/// <reference types="vite-plugin-pwa/client" />
// Registers the service worker (src/pwa/sw.ts). Imported once from main.tsx for its side effect.
import { registerSW } from 'virtual:pwa-register';

if ('serviceWorker' in navigator) {
  registerSW({
    immediate: true,
    onRegisterError(error: unknown) {
      console.warn('AiVee: service worker registration failed', error);
    },
  });
}
