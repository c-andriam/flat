import { useCallback, useMemo, useRef, useState, type ReactNode } from 'react'

import { ToastContext, type Toast, type ToastContextValue, type ToastKind } from './ToastContext'
import { ToastViewport } from './ToastViewport'

const DEFAULT_DURATION = 4_000
const MAX_VISIBLE = 4

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const timers = useRef(new Map<string, number>())

  const dismiss = useCallback((id: string) => {
    const timer = timers.current.get(id)
    if (timer !== undefined) {
      window.clearTimeout(timer)
      timers.current.delete(id)
    }
    setToasts((current) => current.filter((toast) => toast.id !== id))
  }, [])

  const notify = useCallback(
    (message: string, kind: ToastKind = 'info', duration = DEFAULT_DURATION) => {
      const id = crypto.randomUUID()
      setToasts((current) => {
        // Au-delà de quelques toasts la pile masque le contenu : on écarte
        // les plus anciens plutôt que d'empiler indéfiniment.
        const next = [...current, { id, message, kind, duration }]
        return next.length > MAX_VISIBLE ? next.slice(next.length - MAX_VISIBLE) : next
      })
      if (duration > 0) {
        timers.current.set(
          id,
          window.setTimeout(() => dismiss(id), duration),
        )
      }
      return id
    },
    [dismiss],
  )

  const value = useMemo<ToastContextValue>(
    () => ({
      toasts,
      notify,
      dismiss,
      success: (message: string) => notify(message, 'success'),
      error: (message: string) => notify(message, 'error', 6_000),
      warning: (message: string) => notify(message, 'warning'),
      info: (message: string) => notify(message, 'info'),
    }),
    [toasts, notify, dismiss],
  )

  return (
    <ToastContext value={value}>
      {children}
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </ToastContext>
  )
}
