import type { ReactNode } from 'react'

import { cn } from '@/lib/cn'

export interface EmptyStateProps {
  icon?: ReactNode
  title: string
  message?: ReactNode
  action?: ReactNode
  className?: string
}

export function EmptyState({ icon, title, message, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        'rounded-[8px] border border-dashed border-line bg-surface px-6 py-12 text-center text-fg-muted',
        className,
      )}
    >
      {icon ? <div className="mb-4 flex justify-center text-line">{icon}</div> : null}
      <h3 className="mb-2 text-base font-semibold text-fg">{title}</h3>
      {message ? (
        <p className="mx-auto max-w-[420px] text-sm leading-relaxed">{message}</p>
      ) : null}
      {action ? <div className="mt-6 flex justify-center">{action}</div> : null}
    </div>
  )
}
