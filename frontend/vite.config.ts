import { fileURLToPath, URL } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

/**
 * En développement, la SPA tourne sur le serveur Vite mais l'API reste servie
 * par la gateway nginx (certificat auto-signé « localhost »), d'où
 * `secure: false` : sans ça, le proxy refuse le certificat et toute requête
 * /api/v1 échoue avant même d'atteindre FastAPI.
 */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const gateway = env.VITE_DEV_GATEWAY ?? 'https://localhost:8443'

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      host: true,
      port: 5173,
      proxy: {
        '/api': { target: gateway, changeOrigin: true, secure: false },
        '/ws': { target: gateway, changeOrigin: true, secure: false, ws: true },
      },
    },
    build: {
      outDir: 'dist',
      sourcemap: mode !== 'production',
      rollupOptions: {
        output: {
          // Isole les dépendances stables : un déploiement qui ne touche que
          // le code applicatif ne fait pas retélécharger React au navigateur.
          manualChunks: {
            react: ['react', 'react-dom', 'react-router-dom'],
            query: ['@tanstack/react-query'],
          },
        },
      },
    },
  }
})
