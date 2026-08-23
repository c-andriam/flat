/**
 * Connexion au hub temps réel (`/ws`).
 *
 * Le hub diffuse les mêmes événements que ceux publiés par core-api sur Redis.
 * Plutôt que de patcher le cache événement par événement — ce qui exigerait de
 * reconstruire un objet Action complet à partir d'un payload partiel — on
 * invalide la racine concernée et on laisse TanStack Query refaire l'appel.
 */

import type { QueryClient } from '@tanstack/react-query'

import { websocketUrl } from './client'
import { queryKeys } from './queryKeys'
import type { RealtimeEvent, RealtimeEventType } from './types'

export type RealtimeStatus = 'idle' | 'connecting' | 'open' | 'closed'

const RECONNECT_BASE_MS = 1_000
const RECONNECT_MAX_MS = 30_000

function isRealtimeEvent(value: unknown): value is RealtimeEvent {
  return typeof value === 'object' && value !== null && typeof (value as RealtimeEvent).type === 'string'
}

/** Racines de cache à rafraîchir pour un type d'événement donné. */
function affectedKeys(type: RealtimeEventType): readonly (readonly string[])[] {
  switch (type) {
    case 'project_created':
    case 'project_updated':
    case 'project_deleted':
      return [queryKeys.projects.all, queryKeys.reports.all, queryKeys.actions.all]
    case 'action_created':
    case 'action_updated':
    case 'action_deleted':
      return [queryKeys.actions.all, queryKeys.reports.all, queryKeys.projects.all]
    case 'responsable_created':
    case 'responsable_updated':
    case 'responsable_deleted':
      return [queryKeys.responsables.all, queryKeys.actions.all, queryKeys.reports.all]
    case 'slot_created':
    case 'slot_deleted':
    case 'slot_confirmed':
    case 'slot_released':
    case 'slot_moved':
      return [queryKeys.slots.all]
    case 'ping':
      return []
    default:
      return []
  }
}

export interface RealtimeHandlers {
  onStatusChange?: (status: RealtimeStatus) => void
  onEvent?: (event: RealtimeEvent) => void
}

/**
 * Ouvre la connexion et renvoie la fonction d'arrêt.
 * Reconnexion automatique avec backoff exponentiel plafonné à 30 s.
 */
export function connectRealtime(
  token: string,
  queryClient: QueryClient,
  handlers: RealtimeHandlers = {},
): () => void {
  let socket: WebSocket | null = null
  let reconnectTimer: number | undefined
  let attempt = 0
  let disposed = false

  const setStatus = (status: RealtimeStatus) => handlers.onStatusChange?.(status)

  const scheduleReconnect = () => {
    if (disposed) return
    const delay = Math.min(RECONNECT_BASE_MS * 2 ** attempt, RECONNECT_MAX_MS)
    attempt += 1
    reconnectTimer = window.setTimeout(open, delay)
  }

  function open() {
    if (disposed) return
    setStatus('connecting')

    try {
      socket = new WebSocket(websocketUrl(token))
    } catch {
      scheduleReconnect()
      return
    }

    socket.onopen = () => {
      attempt = 0
      setStatus('open')
    }

    socket.onmessage = (message: MessageEvent<string>) => {
      let parsed: unknown
      try {
        parsed = JSON.parse(message.data)
      } catch {
        return
      }
      if (!isRealtimeEvent(parsed)) return
      handlers.onEvent?.(parsed)
      for (const queryKey of affectedKeys(parsed.type)) {
        void queryClient.invalidateQueries({ queryKey })
      }
    }

    socket.onerror = () => {
      // `onclose` suit systématiquement `onerror` : la reconnexion y est gérée
      // une seule fois, sinon deux sockets se relanceraient en parallèle.
      socket?.close()
    }

    socket.onclose = () => {
      socket = null
      if (disposed) return
      setStatus('closed')
      scheduleReconnect()
    }
  }

  open()

  return () => {
    disposed = true
    if (reconnectTimer !== undefined) window.clearTimeout(reconnectTimer)
    if (socket) {
      socket.onclose = null
      socket.close()
      socket = null
    }
    setStatus('idle')
  }
}
