import { useCallback, useEffect, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

import { useScrollLock } from '@/hooks/useScrollLock'
import { cn } from '@/lib/cn'
import { IconClose } from './Icon'

export interface ModalProps {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  footer?: ReactNode
  /** Largeur maximale du dialogue. */
  size?: 'sm' | 'md' | 'lg'
}

const SIZES = {
  sm: 'max-w-[420px]',
  md: 'max-w-[520px]',
  lg: 'max-w-[760px]',
} as const

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'

export function Modal({ open, onClose, title, children, footer, size = 'md' }: ModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const previouslyFocused = useRef<HTMLElement | null>(null)

  useScrollLock(open)

  // Piège à focus : sans lui, Tab sort du dialogue et l'utilisateur au clavier
  // se retrouve à naviguer dans la page masquée derrière l'overlay.
  const onKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onClose()
        return
      }
      if (event.key !== 'Tab') return

      const dialog = dialogRef.current
      if (!dialog) return
      const focusables = Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (element) => element.offsetParent !== null,
      )
      if (focusables.length === 0) return

      const first = focusables[0]
      const last = focusables[focusables.length - 1]
      if (!first || !last) return

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    },
    [onClose],
  )

  useEffect(() => {
    if (!open) return
    previouslyFocused.current = document.activeElement as HTMLElement | null
    const dialog = dialogRef.current
    const target = dialog?.querySelector<HTMLElement>(FOCUSABLE)
    target?.focus()
    return () => {
      // Rendre le focus au déclencheur : sinon il repart en haut de page.
      previouslyFocused.current?.focus?.()
    }
  }, [open])

  if (!open) return null

  return createPortal(
    <div className="fixed inset-0 z-[8000]">
      <div
        className="animate-overlay-in fixed inset-0 cursor-pointer bg-[var(--overlay)]"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onKeyDown={onKeyDown}
        className={cn(
          'animate-dialog-in fixed left-1/2 top-1/2 flex w-[90%] -translate-x-1/2 -translate-y-1/2 flex-col',
          'max-h-[85vh] overflow-hidden rounded-[12px] border border-line bg-surface shadow-overlay',
          SIZES[size],
        )}
      >
        <div className="flex shrink-0 items-center justify-between border-b border-line px-5 py-4">
          <h3 className="text-base font-semibold tracking-[-0.01em] text-fg">{title}</h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="Fermer"
            className="flex cursor-pointer items-center justify-center rounded-[6px] border-none bg-transparent p-1 text-fg-subtle transition-colors hover:bg-surface-hover hover:text-fg"
          >
            <IconClose size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5">{children}</div>

        {footer ? (
          <div className="flex shrink-0 justify-end gap-2 border-t border-line px-5 py-3.5">
            {footer}
          </div>
        ) : null}
      </div>
    </div>,
    document.body,
  )
}
