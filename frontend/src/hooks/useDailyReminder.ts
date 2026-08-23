import { useEffect, useState } from 'react'

import { nowPartsMg, todayMg, toIsoDate, weekdayIndex } from '@/lib/date'
import { holidayFor } from '@/lib/holidays'

/** Premier rappel de la journée, heure locale. */
export const REMINDER_START_HOUR = 10
/** Dernier rappel : au-delà, la journée est finie. */
export const REMINDER_END_HOUR = 18
/** Un rappel toutes les deux heures. */
export const REMINDER_INTERVAL_HOURS = 2

export interface DailyReminder {
  /** Jour ouvrable : ni week-end, ni jour férié malgache. */
  isWorkingDay: boolean
  /** Nombre de rappels écoulés sans que le rapport ait été commencé. */
  ignoredCount: number
  /** Le bandeau doit-il être affiché ? */
  active: boolean
  /** Heure du prochain rappel, `null` si la journée est terminée. */
  nextReminderHour: number | null
}

/**
 * Rappel d'écriture du rapport quotidien.
 *
 * Entièrement calculé côté client : le compteur est une fonction de l'heure et
 * de l'état du rapport, il n'a pas besoin d'être stocké. Cela évite une table
 * de suivi — qui reviendrait à consigner qui ignore ses rappels, ce qui n'est
 * pas le but — et le rend juste après un rechargement de page.
 *
 * Le bandeau ne se duplique jamais : il reste à sa place et affiche le nombre
 * de rappels passés.
 */
export function useDailyReminder(hasContent: boolean): DailyReminder {
  const [tick, setTick] = useState(0)

  // Une minute suffit : les rappels tombent aux heures paires, la précision
  // à la seconde n'apporte rien.
  useEffect(() => {
    const timer = window.setInterval(() => setTick((value) => value + 1), 60_000)
    return () => window.clearInterval(timer)
  }, [])

  void tick

  const today = todayMg()
  const { hour, minute } = nowPartsMg()

  const isWeekend = weekdayIndex(today) >= 5
  const holiday = holidayFor(toIsoDate(today))
  const isWorkingDay = !isWeekend && holiday === null

  const minutesNow = hour * 60 + minute
  const debut = REMINDER_START_HOUR * 60
  const pas = REMINDER_INTERVAL_HOURS * 60
  const dernier = REMINDER_END_HOUR * 60

  let ignoredCount = 0
  if (isWorkingDay && !hasContent && minutesNow >= debut) {
    const ecoules = Math.floor((Math.min(minutesNow, dernier) - debut) / pas) + 1
    ignoredCount = Math.max(0, ecoules)
  }

  let nextReminderHour: number | null = null
  if (isWorkingDay && minutesNow < dernier) {
    const prochain = minutesNow < debut ? debut : debut + (Math.floor((minutesNow - debut) / pas) + 1) * pas
    if (prochain <= dernier) nextReminderHour = Math.floor(prochain / 60)
  }

  return {
    isWorkingDay,
    ignoredCount,
    active: isWorkingDay && !hasContent && ignoredCount > 0,
    nextReminderHour,
  }
}
