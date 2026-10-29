import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { viteSingleFile } from 'vite-plugin-singlefile'

export default defineConfig({
  plugins: [react(), viteSingleFile()],
  build: { outDir: '../evalapp/quickcheck/static', emptyOutDir: true, rollupOptions: { input: 'quickcheck.html' } },
  server: { host: '127.0.0.1', proxy: { '/api': process.env.QUICKCHECK_API_TARGET || 'http://127.0.0.1:8766' } },
})
