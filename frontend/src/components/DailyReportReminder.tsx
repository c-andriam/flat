import { Link } from 'react-router-dom'

import { useTodayReport } from '@/api/queries'
import { useAuth } from '@/auth/useAuth'
import { useDailyReminder } from '@/hooks/useDailyReminder'
import { IconBell } from '@/ui/Icon'

/**
 * Rappel d'écriture du rapport quotidien.
 *
 * Un seul bandeau, qui ne se duplique pas : il reste en place et affiche le
 * nombre de rappels passés depuis le matin. Il disparaît dès que le rapport du
 * jour contient quelque chose — pas seulement quand il est clos, pour ne pas
 * relancer quelqu'un qui a commencé à saisir.
 */
export function DailyReportReminder() {
  const { isAuthenticated } = useAuth()
  const { data } = useTodayReport()
  const { active, ignoredCount, nextReminderHour } = useDailyReminder(
    data?.has_content ?? false,
  )

  if (!isAuthenticated || !active) return null

  return (
    <div className="mb-5 flex flex-wrap items-center gap-3 rounded-[8px] border border-warning/30 bg-warning-subtle px-4 py-3">
      <span className="relative flex shrink-0 items-center justify-center">
        <IconBell size={18} className="text-warning" />
        {ignoredCount > 1 ? (
          <span className="absolute -right-2 -top-2 flex h-4 min-w-4 items-center justify-center rounded-full bg-warning px-1 text-[10px] font-bold leading-none text-white">
            {ignoredCount}
          </span>
        ) : null}
      </span>

      <div className="min-w-0 flex-1 text-[13px] leading-relaxed">
        <p className="font-semibold text-warning">
          {ignoredCount > 1
            ? `${ignoredCount} rappels ignorés — notez ce que vous avez fait`
            : 'Notez ce que vous avez fait aujourd’hui'}
        </p>
        <p className="mt-0.5 text-fg-muted">
          Une ligne suffit à faire disparaître ce rappel.
          {nextReminderHour !== null
            ? ` Prochain rappel à ${String(nextReminderHour).padStart(2, '0')}:00.`
            : ' Dernier rappel de la journée.'}
        </p>
      </div>

      <Link
        to="/rapport-du-jour"
        className="shrink-0 rounded-[6px] border border-warning/40 bg-canvas px-3 py-1.5 text-[13px] font-semibold text-warning no-underline transition-colors hover:bg-warning-subtle"
      >
        Rédiger le rapport
      </Link>
    </div>
  )
}
