import { useMemo } from 'react'

import { addDays, isSameDay, plainDate, startOfWeek, toIsoDate, todayMg } from '@/lib/date'
import { holidayFor } from '@/lib/holidays'

export interface CalendarDay {
  iso: string
  day: number
  isCurrentMonth: boolean
  isToday: boolean
  isWeekend: boolean
  holiday: string | null
}

/**
 * Grille de 6 semaines × 7 jours (42 cellules).
 *
 * Le nombre de semaines est figé — comme dans l'ancienne version Python —
 * pour que la hauteur du calendrier ne saute pas d'un mois à l'autre.
 */
export function useMonthGrid(year: number, month: number): CalendarDay[][] {
  return useMemo(() => {
    const today = todayMg()
    const firstOfMonth = plainDate(year, month, 1)
    const gridStart = startOfWeek(firstOfMonth)

    const weeks: CalendarDay[][] = []
    for (let week = 0; week < 6; week += 1) {
      const days: CalendarDay[] = []
      for (let day = 0; day < 7; day += 1) {
        const date = addDays(gridStart, week * 7 + day)
        const iso = toIsoDate(date)
        days.push({
          iso,
          day: date.getUTCDate(),
          isCurrentMonth: date.getUTCMonth() + 1 === month,
          isToday: isSameDay(date, today),
          isWeekend: day >= 5,
          holiday: holidayFor(iso),
        })
      }
      weeks.push(days)
    }
    return weeks
  }, [year, month])
}
