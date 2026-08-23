# Frontend — SPA DSI TRIMETA Group

Application monopage React 19 + TypeScript, servie en statique par nginx.
Elle consomme les APIs `core-api`, `auth-api` et le hub temps réel via la
gateway, sur la même origine (`/api/v1`, `/ws`).

## Démarrer

```bash
make front-install   # npm ci
make front-dev       # Vite sur http://localhost:5173
make front-check     # typage strict + ESLint
make front-build     # compile dans dist/
```

En développement, Vite proxifie `/api` et `/ws` vers la gateway
(`VITE_DEV_GATEWAY`, défaut `https://localhost:8443`, certificat auto-signé
accepté). Pour que le SSO revienne bien sur le serveur Vite, mettre
`FRONTEND_URL=http://localhost:5173` dans le `.env` de la racine.

## Structure

| Chemin | Rôle |
| --- | --- |
| `src/api/` | Types miroirs des schémas Pydantic, client HTTP, hooks TanStack Query, hub temps réel |
| `src/auth/` | Contexte de session (jeton SSO, rôle RBAC), garde de route |
| `src/theme/` | Bascule clair/sombre, persistée et alignée sur l'OS par défaut |
| `src/ui/` | Kit de composants (boutons, table, modale, toasts, états vides…) |
| `src/components/layout/` | En-tête, barre latérale, coquilles de page |
| `src/features/` | Blocs métier : actions, agenda, créneaux |
| `src/pages/` | Un composant par écran, branché sur les hooks de `src/api` |
| `src/lib/` | Dates en fuseau Madagascar, jours fériés malgaches, formatages |
| `src/styles/` | `tokens.css` (palette GitHub) et thème Tailwind v4 |

## Thème

`src/styles/tokens.css` porte la palette GitHub complète (claire et sombre),
reprise à l'identique de l'ancien frontend Jinja. `src/styles/index.css` la
mappe dans Tailwind avec `@theme inline`, si bien qu'un utilitaire comme
`bg-surface` suit le basculement de thème sans variante `dark:`.

**Ne pas coder de couleur en dur** : passer par les utilitaires
(`bg-canvas`, `text-fg-muted`, `border-line`, `bg-accent-subtle`, …) ou par
les variables `var(--…)` pour les cas que Tailwind ne couvre pas.

## Données

- Lecture et écriture via les hooks de `src/api/queries.ts`.
- Chaque mutation invalide les racines de cache concernées ; le hub temps réel
  fait de même à la réception d'un événement, donc deux navigateurs ouverts
  restent synchronisés.
- Les listes lisent leur total dans l'en-tête `X-Total-Count`.
