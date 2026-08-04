/**
 * Vite config for the React frontend.
 *
 * Tip: `npm run dev` starts a local web server (usually http://127.0.0.1:5173).
 * Tip: `npm run build` creates production files in frontend/dist/.
 */
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    // Vite default is 5173 (not 5713). Keep this explicit for clarity.
    port: 5173,
    // Listen on IPv4 so http://127.0.0.1:5173 works in all browsers.
    // (Without this, some Macs only bind to IPv6 localhost.)
    host: '127.0.0.1',
    strictPort: true,
    // If the React app calls /api/... during local dev, forward those
    // requests to the Django backend so you don't hit CORS during prototyping.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
