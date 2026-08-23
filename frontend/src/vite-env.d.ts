/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base des appels API. Vide = même origine, routée par la gateway nginx. */
  readonly VITE_API_BASE_URL?: string
  /** URL complète du hub temps réel. Vide = `/ws` sur la même origine. */
  readonly VITE_WS_URL?: string
  /** Développement uniquement : cible du proxy Vite. */
  readonly VITE_DEV_GATEWAY?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
