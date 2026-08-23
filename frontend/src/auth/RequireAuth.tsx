import { Navigate, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'

import { Spinner } from '@/ui/Spinner'
import { useAuth } from './useAuth'

/**
 * Garde de route.
 *
 * L'API reste la seule autorité : ce composant n'ajoute pas de sécurité, il
 * évite d'afficher un écran vide qui se remplirait de 401.
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading, token } = useAuth()
  const location = useLocation()

  if (token !== null && isLoading) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center text-fg-muted">
        <Spinner size={22} />
        <span className="ml-3 text-sm">Vérification de la session…</span>
      </div>
    )
  }

  if (!isAuthenticated) {
    return <Navigate to="/connexion" replace state={{ from: location.pathname }} />
  }

  return <>{children}</>
}
