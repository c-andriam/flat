import { createPortal } from 'react-dom'

import { cn } from '@/lib/cn'
import type { Toast, ToastKind } from './ToastContext'
import { IconAlert, IconCheckCircle, IconClose, IconInfo, IconXCircle } from './Icon'

const ACCENTS: Record<ToastKind, string> = {
  success: 'border-l-success [&_[data-toast-icon]]:text-success',
  error: 'border-l-danger [&_[data-toast-icon]]:text-danger',
  warning: 'border-l-warning [&_[data-toast-icon]]:text-warning',
  info: 'border-l-accent [&_[data-toast-icon]]:text-accent',
}

function ToastIcon({ kind }: { kind: ToastKind }) {
  switch (kind) {
    case 'success':
      return <IconCheckCircle size={18} />
    case 'error':
      return <IconXCircle size={18} />
    case 'warning':
      return <IconAlert size={18} />
    case 'info':
      return <IconInfo size={18} />
    default:
      return <IconInfo size={18} />
  }
}

export function ToastViewport({
  toasts,
  onDismiss,
}: {
  toasts: Toast[]
  onDismiss: (id: string) => void
}) {
  return createPortal(
    <div
      aria-live="polite"
      className="pointer-events-none fixed bottom-6 right-6 z-[9000] flex max-w-[400px] flex-col-reverse gap-2 max-[480px]:inset-x-4 max-[480px]:bottom-4 max-[480px]:max-w-none"
    >
      {toasts.map((toast) => (
        <div
          key={toast.id}
          role="alert"
          className={cn(
            'animate-toast-in pointer-events-auto flex items-start gap-2.5 rounded-[8px]',
            'border border-l-[3px] border-line bg-surface p-3 shadow-raised',
            ACCENTS[toast.kind],
          )}
        >
          <div data-toast-icon className="mt-px flex h-5 w-5 shrink-0 items-center justify-center">
            <ToastIcon kind={toast.kind} />
          </div>
          <p className="flex-1 text-[13px] font-medium leading-normal text-fg">{toast.message}</p>
          <button
            type="button"
            onClick={() => onDismiss(toast.id)}
            aria-label="Fermer"
            className="flex shrink-0 cursor-pointer items-center justify-center rounded-[4px] border-none bg-transparent p-0.5 text-fg-subtle transition-colors hover:bg-surface-hover hover:text-fg"
          >
            <IconClose size={14} />
          </button>
        </div>
      ))}
    </div>,
    document.body,
  )
}
