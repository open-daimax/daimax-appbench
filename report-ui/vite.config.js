import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { viteSingleFile } from 'vite-plugin-singlefile'

// 本地报告 UI 单文件构建
//
// 产物 dist/index.html 会被拷贝为
// evalapp/evaluation/results/reporting/templates/report_template.html 并提交入库，
// CLI 生成报告时向其中注入报告 JSON（见 evalapp/evaluation/results/reporting/reporter.py），
// 使用者无需 Node 环境。
export default defineConfig({
  plugins: [react(), viteSingleFile()],
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 8192,
  },
  esbuild: {
    drop: ['console', 'debugger'],
  },
})
