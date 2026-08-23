/**
 * Jours fériés malgaches, en français.
 *
 * Remplace la dépendance Python `holidays` + sa table de traduction
 * malgache→français : la même liste, calculée côté client, évite un appel
 * réseau à chaque changement de mois dans l'agenda.
 */

import { plainDate, toIsoDate, type PlainDate } from './date'

/** Dimanche de Pâques (algorithme grégorien anonyme). */
export function easterSunday(year: number): PlainDate {
  const a = year % 19
  const b = Math.floor(year / 100)
  const c = year % 100
  const d = Math.floor(b / 4)
  const e = b % 4
  const f = Math.floor((b + 8) / 25)
  const g = Math.floor((b - f + 1) / 3)
  const h = (19 * a + b - d - g + 15) % 30
  const i = Math.floor(c / 4)
  const k = c % 4
  const l = (32 + 2 * e + 2 * i - h - k) % 7
  const m = Math.floor((a + 11 * h + 22 * l) / 451)
  const month = Math.floor((h + l - 7 * m + 114) / 31)
  const day = ((h + l - 7 * m + 114) % 31) + 1
  return plainDate(year, month, day)
}

function shift(date: PlainDate, days: number): PlainDate {
  return new Date(date.getTime() + days * 86_400_000)
}

/** N-ième `weekday` (0 = dimanche) du mois ; `nth = -1` pour le dernier. */
function nthWeekdayOfMonth(year: number, month: number, weekday: number, nth: number): PlainDate {
  if (nth < 0) {
    const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate()
    const last = plainDate(year, month, lastDay)
    return shift(last, -((last.getUTCDay() - weekday + 7) % 7))
  }
  const first = plainDate(year, month, 1)
  const offset = (weekday - first.getUTCDay() + 7) % 7
  return shift(first, offset + (nth - 1) * 7)
}

export interface Holiday {
  /** Date ISO `YYYY-MM-DD`. */
  date: string
  name: string
}

const cache = new Map<number, Map<string, string>>()

/** Table `date ISO → libellé` des jours fériés d'une année. */
export function holidaysForYear(year: number): Map<string, string> {
  const cached = cache.get(year)
  if (cached) return cached

  const easter = easterSunday(year)
  const entries: Holiday[] = [
    { date: toIsoDate(plainDate(year, 1, 1)), name: "Jour de l'An" },
    { date: toIsoDate(plainDate(year, 3, 8)), name: 'Journée de la Femme' },
    { date: toIsoDate(plainDate(year, 3, 29)), name: 'Fête des Martyrs' },
    { date: toIsoDate(easter), name: 'Pâques' },
    { date: toIsoDate(shift(easter, 1)), name: 'Lundi de Pâques' },
    { date: toIsoDate(plainDate(year, 5, 1)), name: 'Fête du Travail' },
    { date: toIsoDate(shift(easter, 39)), name: 'Ascension' },
    { date: toIsoDate(shift(easter, 49)), name: 'Pentecôte' },
    { date: toIsoDate(shift(easter, 50)), name: 'Lundi de Pentecôte' },
    { date: toIsoDate(nthWeekdayOfMonth(year, 5, 0, -1)), name: 'Fête des Mères' },
    { date: toIsoDate(nthWeekdayOfMonth(year, 6, 0, 3)), name: 'Fête des Pères' },
    { date: toIsoDate(plainDate(year, 6, 26)), name: "Fête de l'Indépendance" },
    { date: toIsoDate(plainDate(year, 8, 15)), name: 'Assomption' },
    { date: toIsoDate(plainDate(year, 11, 1)), name: 'Toussaint' },
    { date: toIsoDate(plainDate(year, 12, 11)), name: 'Fête de la République' },
    { date: toIsoDate(plainDate(year, 12, 25)), name: 'Noël' },
  ]

  const table = new Map<string, string>()
  for (const entry of entries) {
    // Deux fêtes peuvent tomber le même jour (Fête des Mères / Pentecôte) :
    // on conserve la première, comme le faisait la table côté Python.
    if (!table.has(entry.date)) table.set(entry.date, entry.name)
  }
  cache.set(year, table)
  return table
}

/** Libellé du jour férié correspondant, ou `null`. */
export function holidayFor(isoDate: string): string | null {
  const year = Number(isoDate.slice(0, 4))
  if (!Number.isFinite(year)) return null
  return holidaysForYear(year).get(isoDate) ?? null
}
