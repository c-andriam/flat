import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { connectRealtime, type RealtimeStatus } from '@/api/realtime'
import { useAuth } from '@/auth/useAuth'

/**
 * Maintient la connexion au hub temps réel tant qu'une session est active.
 * Renvoie l'état de la connexion, affiché dans l'en-tête.
 */
export function useRealtime(): RealtimeStatus {
  const { token, isAuthenticated } = useAuth()
  const queryClient = useQueryClient()
  const [status, setStatus] = useState<RealtimeStatus>('idle')

  useEffect(() => {
    if (!token || !isAuthenticated) {
      setStatus('idle')
      return
    }
    return connectRealtime(token, queryClient, { onStatusChange: setStatus })
  }, [token, isAuthenticated, queryClient])

  return status
}
