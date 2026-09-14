import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import basicSsl from '@vitejs/plugin-basic-ssl'

// Phones only expose the microphone on HTTPS, so `npm run dev:https` serves the
// dev server with a self-signed cert (accept the browser warning once).
const https = process.env.VITE_HTTPS === '1'

export default defineConfig({
  plugins: [react(), ...(https ? [basicSsl()] : [])],
  server: {
    port: 5173,
    // Reachable from other devices on the network when using HTTPS.
    host: https ? true : 'localhost',
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
})
