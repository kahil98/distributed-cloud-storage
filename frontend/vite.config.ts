import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig(({mode})=>({base:mode==='github-pages'?'/distributed-cloud-storage/':'/',plugins:[react()]}));
