import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      strategies: 'injectManifest',
      srcDir: 'src',
      // Output file: sw.js. Must match the nginx no-cache rule (frontend/nginx.conf:14
      // `location = /sw.js`). Do not rename without updating that rule.
      filename: 'sw.ts',
      registerType: 'autoUpdate',
      injectRegister: 'auto',
      manifest: {
        name: 'RC Scout',
        short_name: 'RC Scout',
        description: 'Dein persönlicher RC-Flohmarkt-Scout',
        start_url: '/',
        display: 'standalone',
        background_color: '#0f0f23',
        theme_color: '#0f0f23',
        orientation: 'portrait',
        icons: [
          { src: '/favicon.svg',                  sizes: 'any',     type: 'image/svg+xml' },
          { src: '/icons/icon-192.png',           sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: '/icons/icon-512.png',           sizes: '512x512', type: 'image/png', purpose: 'any' },
          { src: '/icons/icon-maskable-192.png',  sizes: '192x192', type: 'image/png', purpose: 'maskable' },
          { src: '/icons/icon-maskable-512.png',  sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      injectManifest: {
        globPatterns: ['**/*.{js,css,html,ico,png,svg,webmanifest}'],
      },
      devOptions: { enabled: false },
    }),
  ],
  server: {
    proxy: {
      '/api': {
        target: process.env.API_PROXY_TARGET ?? 'http://localhost:8002',
        changeOrigin: true,
      },
    },
    watch: { usePolling: true },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
  },
});
