import { useContext } from 'react'

import { ToastContext, type ToastContextValue } from './ToastContext'

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext)
  if (context === null) {
    throw new Error('useToast doit être utilisé à l’intérieur de <ToastProvider>.')
  }
  return context
}
