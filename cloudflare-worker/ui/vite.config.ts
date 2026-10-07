import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  build: {
    target: 'safari15',
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
  },
})
