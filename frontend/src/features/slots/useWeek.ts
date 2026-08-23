import { useEffect, useMemo, useState } from 'react'

import {
  DAYS_FR_SHORT,
  DAY_KEYS,
  addDays,
  isSameDay,
  monthNameFr,
  nowPartsMg,
  startOfWeek,
  toIsoDate,
  todayMg,
  type DayKey,
} from '@/lib/date'

/** Hauteur d'un quart d'heure, en pixels. */
export const SLOT_HEIGHT_PX = 30

export const SLOT_START_HOUR = 8
export const SLOT_END_HOUR = 17
export const LUNCH_HOUR = 12
export const SLOT_MINUTES = 15

/**
 * Délai minimal entre maintenant et le début d'un créneau réservable.
 * Sans lui, on pourrait poser un rendez-vous qui commence dans la minute.
 */
export const MIN_LEAD_MINUTES = 15

export interface WeekDay {
  key: DayKey
  name: string
  dayOfMonth: number
  month: number
  iso: string
  isToday: boolean
  isPast: boolean
  isWeekend: boolean
}

export interface WeekModel {
  days: WeekDay[]
  label: string
  /** Minutes écoulées depuis minuit, heure de Madagascar. */
  nowMinutes: number
  todayIso: string
}

export interface SlotRow {
  hour: number
  minute: number
  /** Minutes depuis minuit — sert aux comparaisons d'horaire. */
  minutesOfDay: number
  time: string
  endTime: string
  isHourMark: boolean
  isHalfHour: boolean
}

/**
 * Ré-évalue l'heure courante à chaque minute.
 *
 * Un onglet laissé ouvert toute la matinée continuait sinon d'afficher comme
 * réservables des créneaux déjà passés.
 */
function useMinuteTick(): number {
  const [tick, setTick] = useState(0)
  useEffect(() => {
    const timer = window.setInterval(() => setTick((value) => value + 1), 60_000)
    return () => window.clearInterval(timer)
  }, [])
  return tick
}

/** Semaine du lundi au dimanche, décalée de `weekOffset` semaines. */
export function useWeek(weekOffset: number): WeekModel {
  const tick = useMinuteTick()

  return useMemo(() => {
    void tick // dépendance volontaire : force le recalcul à chaque minute.

    const today = todayMg()
    const { hour, minute } = nowPartsMg()
    const monday = addDays(startOfWeek(today), weekOffset * 7)
    const sunday = addDays(monday, 6)

    const days: WeekDay[] = Array.from({ length: 7 }, (_, index) => {
      const date = addDays(monday, index)
      return {
        key: DAY_KEYS[index] as DayKey,
        name: DAYS_FR_SHORT[index] ?? '',
        dayOfMonth: date.getUTCDate(),
        month: date.getUTCMonth() + 1,
        iso: toIsoDate(date),
        isToday: isSameDay(date, today),
        isPast: date.getTime() < today.getTime(),
        isWeekend: index >= 5,
      }
    })

    const mondayMonth = monthNameFr(monday.getUTCMonth() + 1)
    const sundayMonth = monthNameFr(sunday.getUTCMonth() + 1)
    const label =
      monday.getUTCMonth() === sunday.getUTCMonth()
        ? `${monday.getUTCDate()} — ${sunday.getUTCDate()} ${mondayMonth} ${monday.getUTCFullYear()}`
        : `${monday.getUTCDate()} ${mondayMonth} — ${sunday.getUTCDate()} ${sundayMonth} ${sunday.getUTCFullYear()}`

    return { days, label, nowMinutes: hour * 60 + minute, todayIso: toIsoDate(today) }
  }, [weekOffset, tick])
}

/** Les lignes de la grille : un quart d'heure par ligne, de 8 h à 17 h. */
export function buildSlotRows(): SlotRow[] {
  const rows: SlotRow[] = []
  for (let hour = SLOT_START_HOUR; hour < SLOT_END_HOUR; hour += 1) {
    for (let quarter = 0; quarter < 60 / SLOT_MINUTES; quarter += 1) {
      const minute = quarter * SLOT_MINUTES
      const endMinute = minute + SLOT_MINUTES
      const endHour = endMinute === 60 ? hour + 1 : hour
      rows.push({
        hour,
        minute,
        minutesOfDay: hour * 60 + minute,
        time: `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`,
        endTime: `${String(endHour).padStart(2, '0')}:${String(endMinute % 60).padStart(2, '0')}`,
        isHourMark: minute === 0,
        isHalfHour: minute === 30,
      })
    }
  }
  return rows
}

/** Identifiant stable d'un créneau, ex. `lun_08:15`. */
export function slotKey(day: WeekDay, row: SlotRow): string {
  return `${day.key}_${row.time}`
}

/**
 * Un créneau est indisponible s'il tombe le week-end, sur la pause déjeuner,
 * un jour passé, ou s'il commence dans moins de `MIN_LEAD_MINUTES`.
 */
export function isSlotDisabled(day: WeekDay, row: SlotRow, week: WeekModel): boolean {
  if (day.isWeekend) return true
  if (row.hour === LUNCH_HOUR) return true
  if (day.isPast) return true
  if (!day.isToday) return false
  return row.minutesOfDay < week.nowMinutes + MIN_LEAD_MINUTES
}

export interface SlotRun {
  /** Index de la première ligne du bloc. */
  startIndex: number
  /** Nombre de quarts d'heure consécutifs. */
  length: number
  start: string
  end: string
}

/** Regroupe les quarts d'heure contigus d'un jour en blocs affichables. */
export function buildRuns(day: WeekDay, rows: SlotRow[], selected: ReadonlySet<string>): SlotRun[] {
  const runs: SlotRun[] = []
  let index = 0
  while (index < rows.length) {
    const row = rows[index]
    if (!row || !selected.has(slotKey(day, row))) {
      index += 1
      continue
    }
    let end = index
    while (end + 1 < rows.length) {
      const next = rows[end + 1]
      // La contiguïté visuelle suffit : deux quarts d'heure séparés par la
      // pause déjeuner ne sont jamais tous deux sélectionnables.
      if (!next || !selected.has(slotKey(day, next))) break
      end += 1
    }
    runs.push({
      startIndex: index,
      length: end - index + 1,
      start: row.time,
      end: rows[end]?.endTime ?? row.endTime,
    })
    index = end + 1
  }
  return runs
}

/** Durée d'une sélection, formatée « 1 h 30 ». */
export function formatDuration(slotCount: number): string {
  const total = slotCount * SLOT_MINUTES
  const hours = Math.floor(total / 60)
  const minutes = total % 60
  if (hours === 0) return `${minutes} min`
  return minutes === 0 ? `${hours} h` : `${hours} h ${minutes}`
}

// ─── Modèle d'affichage des créneaux serveur ───

export type SlotTone = 'selected' | 'open' | 'pending' | 'confirmed' | 'mine' | 'busy'

/** Un bloc dessiné par-dessus la grille : plage sélectionnée ou créneau existant. */
export interface SlotBlock {
  id: string
  dayKey: string
  /** Index de la première ligne de quart d'heure. */
  startIndex: number
  /** Nombre de quarts d'heure couverts. */
  length: number
  tone: SlotTone
  label: string
  title?: string
  /** Cliquable — retrait d'une disponibilité, annulation d'un rendez-vous. */
  actionable?: boolean
  /**
   * Tous les créneaux couverts par le bloc.
   *
   * Un bloc peut fusionner plusieurs quarts d'heure : n'agir que sur le
   * premier laissait le reste de la plage en place, ce qui donnait
   * l'impression que le retrait n'avait pas fonctionné.
   */
  slotIds: string[]
}

export interface CellState {
  /** L'utilisateur peut inclure cette case dans une sélection. */
  selectable: boolean
  /** Hachurée : hors plage ouvrable, passée, ou trop proche. */
  blocked: boolean
  /**
   * Disponibilité offerte, à mettre en évidence.
   *
   * Côté preneur, une case libre se distinguait mal d'une case vide : rien ne
   * signalait où l'on pouvait cliquer.
   */
  available?: boolean
  /** Le quart d'heure peut être retiré — croix au survol. */
  deletable?: boolean
  /** Le bloc auquel appartient la case peut être déplacé par glisser. */
  movable?: boolean
}

/** `HH:MM` en heure de Madagascar à partir d'un horodatage ISO. */
export function localTimeLabel(iso: string): string {
  const parsed = new Date(iso)
  if (Number.isNaN(parsed.getTime())) return '--:--'
  const shifted = new Date(parsed.getTime() + 3 * 3_600_000)
  return `${String(shifted.getUTCHours()).padStart(2, '0')}:${String(shifted.getUTCMinutes()).padStart(2, '0')}`
}

/** Date ISO (`YYYY-MM-DD`) en heure de Madagascar. */
export function localDayIso(iso: string): string {
  const parsed = new Date(iso)
  if (Number.isNaN(parsed.getTime())) return ''
  return new Date(parsed.getTime() + 3 * 3_600_000).toISOString().slice(0, 10)
}

/**
 * Horodatage ISO avec fuseau métier, à partir d'un jour et d'un horaire local.
 *
 * Construit la chaîne à la main plutôt que via `Date` : passer par un objet
 * Date appliquerait le fuseau du navigateur et décalerait le rendez-vous pour
 * un utilisateur en déplacement.
 */
export function toMgIso(dayIso: string, time: string): string {
  return `${dayIso}T${time}:00+03:00`
}
