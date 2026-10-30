// Node globals are available when Vite loads this file (no @types/node needed).
declare const process: { env: Record<string, string | undefined> }

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The dev server proxies API + WebSocket calls to the backend (port from
// start.sh, default 8000), so the browser only ever talks to one origin.
const backendPort = process.env.BACKEND_PORT || '8000'
const backendHost = process.env.BACKEND_HOST || '127.0.0.1'

export default defineConfig({
  plugins: [react()],
  server: {
    port: Number(process.env.FRONTEND_PORT || 5173),
    host: true, // reachable from other devices on the LAN (phone, tablet)
    proxy: {
      '/api': `http://${backendHost}:${backendPort}`,
      '/health': `http://${backendHost}:${backendPort}`,
      '/ws': {
        target: `ws://${backendHost}:${backendPort}`,
        ws: true,
      },
    },
  },
  preview: {
    proxy: {
      '/api': `http://${backendHost}:${backendPort}`,
      '/ws': { target: `ws://${backendHost}:${backendPort}`, ws: true },
    },
  },
  build: {
    target: 'es2020',
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        // Long-lived vendor chunk: app updates don't re-download React.
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom'],
        },
      },
    },
  },
})
