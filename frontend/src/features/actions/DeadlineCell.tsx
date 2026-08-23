import { daysBetween, formatDateShort, fromIsoDate, todayMg } from '@/lib/date'
import { cn } from '@/lib/cn'
import type { ActionStatus, IsoDate } from '@/api/types'

/**
 * Échéance + criticité.
 *
 * Le retard n'est mis en évidence que sur une action encore ouverte : une
 * action terminée en retard reste un fait historique, pas une alerte.
 */
export function DeadlineCell({
  deadline,
  status,
}: {
  deadline: IsoDate | null
  status: ActionStatus
}) {
  if (!deadline) return <span className="text-fg-subtle">—</span>

  const date = fromIsoDate(deadline)
  const left = date ? daysBetween(todayMg(), date) : null
  const closed = status === 'termine'

  return (
    <span
      className={cn(
        'whitespace-nowrap tabular-nums',
        !closed && left !== null && left < 0 && 'font-semibold text-danger',
        !closed && left !== null && left >= 0 && left <= 3 && 'font-semibold text-warning',
      )}
      title={left === null ? undefined : left < 0 ? `${Math.abs(left)} jour(s) de retard` : `${left} jour(s) restant(s)`}
    >
      {formatDateShort(deadline)}
    </span>
  )
}
