import type { ReactNode } from 'react'

import { cn } from '@/lib/cn'

export type BadgeTone = 'neutral' | 'blue' | 'green' | 'orange' | 'red' | 'purple'

const TONES: Record<BadgeTone, string> = {
  neutral: 'bg-inset text-fg-muted border-line',
  blue: 'bg-accent-subtle text-accent border-accent/25',
  green: 'bg-success-subtle text-success border-success/25',
  orange: 'bg-warning-subtle text-warning border-warning/25',
  red: 'bg-danger-subtle text-danger border-danger/25',
  purple: 'bg-info-subtle text-info border-info/25',
}

export function Badge({
  tone = 'neutral',
  children,
  className,
}: {
  tone?: BadgeTone
  children: ReactNode
  className?: string
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5',
        'text-[11px] font-semibold leading-5',
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}
