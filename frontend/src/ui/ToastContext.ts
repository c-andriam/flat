import { createContext } from 'react'

export type ToastKind = 'success' | 'error' | 'warning' | 'info'

export interface Toast {
  id: string
  message: string
  kind: ToastKind
  /** Durée d'affichage en ms ; `0` garde le toast jusqu'à fermeture manuelle. */
  duration: number
}

export interface ToastContextValue {
  toasts: Toast[]
  notify: (message: string, kind?: ToastKind, duration?: number) => string
  success: (message: string) => string
  error: (message: string) => string
  warning: (message: string) => string
  info: (message: string) => string
  dismiss: (id: string) => void
}

/** Séparé du provider pour que le rafraîchissement à chaud reste opérant. */
export const ToastContext = createContext<ToastContextValue | null>(null)
