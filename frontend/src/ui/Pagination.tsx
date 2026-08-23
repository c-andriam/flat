import { Button } from './Button'
import { IconChevronLeft, IconChevronRight } from './Icon'

export interface PaginationProps {
  total: number
  limit: number
  offset: number
  onOffsetChange: (offset: number) => void
}

export function Pagination({ total, limit, offset, onOffsetChange }: PaginationProps) {
  if (total <= limit) return null

  const page = Math.floor(offset / limit) + 1
  const pageCount = Math.max(1, Math.ceil(total / limit))
  const from = total === 0 ? 0 : offset + 1
  const to = Math.min(offset + limit, total)

  return (
    <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
      <p className="text-[12px] text-fg-muted">
        <span className="font-semibold text-fg">
          {from}–{to}
        </span>{' '}
        sur {total}
      </p>
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          variant="secondary"
          disabled={offset === 0}
          onClick={() => onOffsetChange(Math.max(0, offset - limit))}
          aria-label="Page précédente"
        >
          <IconChevronLeft size={14} />
        </Button>
        <span className="text-[12px] tabular-nums text-fg-muted">
          {page} / {pageCount}
        </span>
        <Button
          size="sm"
          variant="secondary"
          disabled={offset + limit >= total}
          onClick={() => onOffsetChange(offset + limit)}
          aria-label="Page suivante"
        >
          <IconChevronRight size={14} />
        </Button>
      </div>
    </div>
  )
}
