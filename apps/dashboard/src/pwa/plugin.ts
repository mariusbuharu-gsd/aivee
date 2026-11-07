// Build-time PWA setup (imported by vite.config.ts, runs in Node): web app manifest and the
// service worker in src/pwa/sw.ts, compiled by vite-plugin-pwa (injectManifest).
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { VitePWA } from 'vite-plugin-pwa';

const styles = () => readFileSync(fileURLToPath(new URL('../styles.css', import.meta.url)), 'utf8');

/** Read a colour token from the `:root` block of styles.css, so the manifest never drifts. */
export function token(name: string, css: string = styles()): string {
  const match = new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{3,8})\\b`).exec(css);
  if (!match?.[1]) throw new Error(`token --${name} not found in styles.css`);
  return match[1].toUpperCase();
}

export function pwa() {
  return VitePWA({
    strategies: 'injectManifest',
    srcDir: 'src/pwa',
    filename: 'sw.ts',
    // Registered by src/pwa/register.ts, not by an injected script.
    injectRegister: false,
    registerType: 'autoUpdate',
    includeAssets: ['favicon.svg', 'icons/*.png'],
    injectManifest: { globPatterns: ['**/*.{js,css,html,svg,png,woff2}'] },
    devOptions: { enabled: true, type: 'module', navigateFallback: 'index.html' },
    manifest: {
      id: '/',
      name: 'AiVee',
      short_name: 'AiVee',
      description:
        'Alerte pentru ospătari: afli pe loc când o masă așteaptă, un client ridică mâna sau se face coadă la intrare.',
      lang: 'ro',
      dir: 'ltr',
      start_url: '/',
      scope: '/',
      display: 'standalone',
      orientation: 'any',
      theme_color: token('ink'),
      background_color: token('ground'),
      categories: ['business', 'productivity'],
      icons: [
        { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
        { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
        {
          src: '/icons/maskable-192.png',
          sizes: '192x192',
          type: 'image/png',
          purpose: 'maskable',
        },
        {
          src: '/icons/maskable-512.png',
          sizes: '512x512',
          type: 'image/png',
          purpose: 'maskable',
        },
      ],
      shortcuts: [{ name: 'Alerte', short_name: 'Alerte', url: '/alerte' }],
    },
  });
}
