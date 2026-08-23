import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'

import type { ApiError } from '@/api/client'
import { getToken, loginUrl, setToken, setUnauthorizedHandler } from '@/api/client'
import { auth as authApi } from '@/api/endpoints'
import { queryKeys } from '@/api/queryKeys'
import type { CurrentUser, UserRole } from '@/api/types'
import { AuthContext, type AuthContextValue } from './AuthContext'

/**
 * Récupère le jeton déposé par auth-api dans le fragment d'URL
 * (`/#token=…` à la fin du callback SSO) puis nettoie la barre d'adresse :
 * un JWT visible dans l'historique du navigateur est une fuite gratuite.
 */
function consumeTokenFromHash(): string | null {
  const hash = window.location.hash
  if (!hash.startsWith('#token=')) return null
  const token = decodeURIComponent(hash.slice('#token='.length))
  window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`)
  return token || null
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [token, setTokenState] = useState<string | null>(() => {
    const fromHash = consumeTokenFromHash()
    if (fromHash) {
      setToken(fromHash)
      return fromHash
    }
    return getToken()
  })

  const logout = useCallback(() => {
    setToken(null)
    setTokenState(null)
    queryClient.clear()
  }, [queryClient])

  // Un 401 sur n'importe quel appel signifie que le jeton est mort : purger
  // ici évite que chaque page ait à gérer le cas.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      setTokenState(null)
      queryClient.clear()
    })
    return () => setUnauthorizedHandler(null)
  }, [queryClient])

  const meQuery = useQuery<CurrentUser, ApiError>({
    queryKey: queryKeys.me,
    queryFn: ({ signal }) => authApi.me(signal),
    enabled: token !== null,
    retry: (failureCount, error) => !error.isAuthError && failureCount < 2,
    staleTime: 5 * 60_000,
  })

  const login = useCallback(() => {
    window.location.assign(loginUrl())
  }, [])

  const user = meQuery.data ?? null
  const role = user?.role ?? null
  const linkedResponsables = useMemo(() => user?.linked_responsables ?? [], [user])
  const linkedResponsableIds = useMemo(
    () => new Set(linkedResponsables.map((fiche) => fiche.id)),
    [linkedResponsables],
  )

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      token,
      isLoading: token !== null && meQuery.isLoading,
      isAuthenticated: user !== null,
      error: meQuery.error ?? null,
      login,
      logout,
      hasRole: (...roles: UserRole[]) => (role === null ? false : roles.includes(role)),
      canWrite: role === 'admin' || role === 'responsable_si',
      seesAllData: user?.sees_all_data ?? false,
      linkedResponsables,
      linkedResponsableIds,
      isUnlinked: user !== null && !user.sees_all_data && linkedResponsables.length === 0,
    }),
    [
      user,
      token,
      meQuery.isLoading,
      meQuery.error,
      login,
      logout,
      role,
      linkedResponsables,
      linkedResponsableIds,
    ],
  )

  return <AuthContext value={value}>{children}</AuthContext>
}
