import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { viteSingleFile } from 'vite-plugin-singlefile'
export default defineConfig({
  plugins: [react(), viteSingleFile()],
  build: { outDir: '../evalapp/studio/static', emptyOutDir: true, rollupOptions: { input: 'studio.html' } },
  server: { host: '127.0.0.1', proxy: Object.fromEntries(['/api', '/quickcheck.html', '/studio-reports'].map(path => [path, 'http://127.0.0.1:8766'])) },
})
