import { cn } from '@/lib/cn'
import { DAYS_FR_SHORT } from '@/lib/date'
import type { CalendarDay } from './useMonthGrid'

export interface DayMarker {
  /** Libellé affiché dans la pastille. */
  label: string
  tone: 'accent' | 'warning' | 'danger' | 'success' | 'mine'
  title?: string
}

const MARKER_TONES = {
  accent: 'bg-accent-subtle text-accent',
  warning: 'bg-warning-subtle text-warning',
  danger: 'bg-danger-subtle text-danger',
  success: 'bg-success-subtle text-success',
  // Ses propres échéances : teinte distincte et bordure, pour qu'elles se
  // détachent du volume des autres sans dépendre d'un code couleur de statut.
  mine: 'bg-info-subtle text-info ring-1 ring-info/40 font-bold',
} as const

export function MonthCalendar({
  weeks,
  markersByDate,
  onSelectDay,
  selectedDate,
}: {
  weeks: CalendarDay[][]
  markersByDate?: Map<string, DayMarker[]>
  onSelectDay?: (iso: string) => void
  selectedDate?: string | null
}) {
  return (
    <div className="flex h-full flex-1 flex-col overflow-x-auto rounded-[8px] border border-line bg-canvas">
      <div className="grid min-w-[600px] grid-cols-7 border-b border-line">
        {DAYS_FR_SHORT.map((day) => (
          <div
            key={day}
            className="border-r border-line px-0 pb-1 pt-3 text-center text-[11px] font-medium uppercase text-fg-muted last:border-r-0"
          >
            {day}
          </div>
        ))}
      </div>

      <div className="grid min-w-[600px] flex-1 auto-rows-fr grid-cols-7">
        {weeks.flat().map((day) => {
          const markers = markersByDate?.get(day.iso) ?? []
          const selected = selectedDate === day.iso
          const Cell = onSelectDay ? 'button' : 'div'
          return (
            <Cell
              key={day.iso}
              {...(onSelectDay
                ? { type: 'button' as const, onClick: () => onSelectDay(day.iso) }
                : {})}
              className={cn(
                'flex min-h-20 flex-col items-center gap-1 overflow-hidden border-b border-r border-line p-1 text-left',
                '[&:nth-child(7n)]:border-r-0',
                day.isWeekend && 'bg-inset/40',
                onSelectDay && 'cursor-pointer transition-colors hover:bg-surface-hover',
                selected && 'bg-accent-subtle',
              )}
            >
              <span
                className={cn(
                  'mt-0.5 flex h-6 w-6 items-center justify-center rounded-full text-[12px] font-medium',
                  day.isCurrentMonth ? 'text-fg' : 'text-fg-subtle',
                  day.isToday && 'bg-accent font-semibold text-white',
                )}
              >
                {day.day}
              </span>

              {day.holiday ? (
                <span
                  title={day.holiday}
                  className="w-full truncate rounded-[4px] bg-success-subtle px-1 py-0.5 text-center text-[10px] font-semibold leading-tight text-success"
                >
                  {day.holiday}
                </span>
              ) : null}

              {markers.slice(0, 2).map((marker, index) => (
                <span
                  key={`${day.iso}-${index}`}
                  title={marker.title ?? marker.label}
                  className={cn(
                    'w-full truncate rounded-[4px] px-1 py-0.5 text-center text-[10px] font-semibold leading-tight',
                    MARKER_TONES[marker.tone],
                  )}
                >
                  {marker.label}
                </span>
              ))}

              {markers.length > 2 ? (
                <span className="text-[10px] font-medium text-fg-subtle">
                  +{markers.length - 2}
                </span>
              ) : null}
            </Cell>
          )
        })}
      </div>
    </div>
  )
}
