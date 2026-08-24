import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// base './' — чтобы прод-сборка работала из file:// внутри Electron.
export default defineConfig({
  plugins: [react()],
  base: './',
  server: { port: 5173, strictPort: true },
  build: { outDir: 'dist', emptyOutDir: true },
});
