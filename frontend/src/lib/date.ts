/**
 * Utilitaires de date en heure de Madagascar (UTC+3).
 *
 * L'ancien frontend calculait « aujourd'hui » côté serveur avec un fuseau
 * figé à +3. Le faire côté client avec le fuseau du navigateur ferait
 * dériver l'agenda pour un utilisateur en déplacement : on garde donc le
 * fuseau métier explicite.
 */

export const MG_TZ_OFFSET_HOURS = 3

export const MONTHS_FR = [
  'Janvier',
  'Février',
  'Mars',
  'Avril',
  'Mai',
  'Juin',
  'Juillet',
  'Août',
  'Septembre',
  'Octobre',
  'Novembre',
  'Décembre',
] as const

export const DAYS_FR_SHORT = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim'] as const
export const DAY_KEYS = ['lun', 'mar', 'mer', 'jeu', 'ven', 'sam', 'dim'] as const

export type DayKey = (typeof DAY_KEYS)[number]

/** Date civile sans heure, manipulée en UTC pour éviter toute dérive DST. */
export type PlainDate = Date

export function monthNameFr(month: number): string {
  return MONTHS_FR[month - 1] ?? ''
}

/** Construit une date « civile » ancrée à minuit UTC. */
export function plainDate(year: number, month: number, day: number): PlainDate {
  return new Date(Date.UTC(year, month - 1, day))
}

/** Aujourd'hui, tel que le voit un utilisateur à Madagascar. */
export function todayMg(now: Date = new Date()): PlainDate {
  const shifted = new Date(now.getTime() + MG_TZ_OFFSET_HOURS * 3_600_000)
  return plainDate(shifted.getUTCFullYear(), shifted.getUTCMonth() + 1, shifted.getUTCDate())
}

/** Heure et minute courantes à Madagascar. */
export function nowPartsMg(now: Date = new Date()): { hour: number; minute: number } {
  const shifted = new Date(now.getTime() + MG_TZ_OFFSET_HOURS * 3_600_000)
  return { hour: shifted.getUTCHours(), minute: shifted.getUTCMinutes() }
}

export function addDays(date: PlainDate, days: number): PlainDate {
  return new Date(date.getTime() + days * 86_400_000)
}

export function addMonths(year: number, month: number, delta: number): { year: number; month: number } {
  const zeroBased = year * 12 + (month - 1) + delta
  return { year: Math.floor(zeroBased / 12), month: (((zeroBased % 12) + 12) % 12) + 1 }
}

/** Index 0 = lundi, 6 = dimanche (la semaine métier commence le lundi). */
export function weekdayIndex(date: PlainDate): number {
  return (date.getUTCDay() + 6) % 7
}

/** Lundi de la semaine contenant `date`. */
export function startOfWeek(date: PlainDate): PlainDate {
  return addDays(date, -weekdayIndex(date))
}

export function toIsoDate(date: PlainDate): string {
  return date.toISOString().slice(0, 10)
}

export function fromIsoDate(iso: string): PlainDate | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  if (!match) return null
  return plainDate(Number(match[1]), Number(match[2]), Number(match[3]))
}

export function isSameDay(a: PlainDate, b: PlainDate): boolean {
  return a.getTime() === b.getTime()
}

/** Écart en jours entiers, positif si `to` est dans le futur. */
export function daysBetween(from: PlainDate, to: PlainDate): number {
  return Math.round((to.getTime() - from.getTime()) / 86_400_000)
}

/** « 24/08/2026 » — format court utilisé dans les tableaux. */
export function formatDateShort(value: string | null | undefined): string {
  if (!value) return '—'
  const date = fromIsoDate(value)
  if (!date) return '—'
  const dd = String(date.getUTCDate()).padStart(2, '0')
  const mm = String(date.getUTCMonth() + 1).padStart(2, '0')
  return `${dd}/${mm}/${date.getUTCFullYear()}`
}

/** « 24 août 2026 » — format long des en-têtes. */
export function formatDateLong(value: string | null | undefined): string {
  if (!value) return '—'
  const date = fromIsoDate(value)
  if (!date) return '—'
  const month = monthNameFr(date.getUTCMonth() + 1).toLowerCase()
  return `${date.getUTCDate()} ${month} ${date.getUTCFullYear()}`
}

/** « 24/08/2026 à 14:32 » à partir d'un datetime ISO du backend. */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '—'
  const shifted = new Date(parsed.getTime() + MG_TZ_OFFSET_HOURS * 3_600_000)
  const dd = String(shifted.getUTCDate()).padStart(2, '0')
  const mm = String(shifted.getUTCMonth() + 1).padStart(2, '0')
  const hh = String(shifted.getUTCHours()).padStart(2, '0')
  const mi = String(shifted.getUTCMinutes()).padStart(2, '0')
  return `${dd}/${mm}/${shifted.getUTCFullYear()} à ${hh}:${mi}`
}

/** « il y a 3 jours », « dans 2 h » — pour les colonnes d'échéance. */
export function formatRelativeDays(days: number | null | undefined): string {
  if (days === null || days === undefined) return '—'
  if (days === 0) return "aujourd'hui"
  if (days === 1) return 'demain'
  if (days === -1) return 'hier'
  return days > 0 ? `dans ${days} jours` : `il y a ${Math.abs(days)} jours`
}
