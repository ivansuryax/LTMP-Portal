import { defineConfig } from 'vite';
import react from 'react';
// React is mounted in src/main.jsx. The original HTML/CSS/JS are bridged
// in phase 1 to preserve existing UI while incrementally porting modules.
export default defineConfig({
  server: { port: 5173, proxy: { '/api': 'http://127.0.0.1:8000' } },
  preview: { port: 4173 },
  build: { target: 'es2022' }
});
