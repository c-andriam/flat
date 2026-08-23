import { QueryClient } from '@tanstack/react-query'

import { ApiError } from '@/api/client'

/**
 * Réglages globaux du cache.
 *
 * `staleTime` à 30 s : les écrans se rafraîchissent surtout par le hub temps
 * réel, un refetch systématique au moindre focus n'apporterait rien.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        gcTime: 5 * 60_000,
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => {
          // Inutile de réessayer un 401/403/404 : la réponse ne changera pas.
          if (error instanceof ApiError && (error.isAuthError || error.isNotFound)) return false
          return failureCount < 2
        },
      },
      mutations: {
        retry: false,
      },
    },
  })
}
