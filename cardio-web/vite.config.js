import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  // Tailwind v4：Vite 插件替代 PostCSS（配置升格为 CSS-first @theme）
  plugins: [react(), tailwindcss()],
  server: { host: true, port: 5173 },
  build: { outDir: 'dist' },
})
