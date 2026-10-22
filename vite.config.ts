import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        // Libraries in their own long-cached chunks (vercel.json: immutable /assets), so a deploy
        // that only changes app code doesn't make browsers download the chart library again.
        manualChunks(id) {
          if (!id.includes('node_modules')) return
          if (/node_modules[\\/](recharts|d3-[^\\/]+|victory-vendor|internmap|decimal\.js-light|react-smooth|recharts-scale|lodash|eventemitter3|tiny-invariant|clsx)[\\/]/.test(id)) return 'charts'
          if (/node_modules[\\/](react|react-dom|scheduler)[\\/]/.test(id)) return 'react'
        },
      },
    },
  },
})
