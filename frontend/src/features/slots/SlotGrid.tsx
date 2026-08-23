import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'

import { useElementWidth } from '@/hooks/useElementWidth'
import { cn } from '@/lib/cn'
import {
  SLOT_HEIGHT_PX,
  buildSlotRows,
  slotKey,
  type CellState,
  type SlotBlock,
  type SlotTone,
  type WeekModel,
} from './useWeek'

/** Largeur de la colonne des heures, en pixels. */
const TIME_COL_PX = 56
/** En dessous, la grille défile horizontalement plutôt que de se comprimer. */
const MIN_DAY_COL_PX = 74

export interface GestureResult {
  /** Sélection résultante. */
  next: ReadonlySet<string>
  /** Clés ajoutées par le geste. */
  added: string[]
  /** Clés retirées par le geste. */
  removed: string[]
}

export interface SlotGridProps {
  week: WeekModel
  blocks: SlotBlock[]
  getCellState: (dayKey: string, rowIndex: number) => CellState
  selected: ReadonlySet<string>
  /** Appelé une seule fois, à la fin du geste (clic simple ou tracé). */
  onGesture: (result: GestureResult) => void
  /** Retrait d'un quart d'heure — croix au survol. */
  onCellDelete?: (dayKey: string, rowIndex: number) => void
  /** Déplacement d'un bloc, exprimé en nombre de quarts d'heure. */
  onBlockMove?: (block: SlotBlock, deltaRows: number) => void
  selectionLabel?: string
}

interface MoveState {
  block: SlotBlock
  /** Ligne où le bloc a été saisi. */
  grab: number
  /** Ligne survolée à l'instant. */
  head: number
}

interface DragState {
  dayKey: string
  anchor: number
  head: number
  mode: 'add' | 'remove'
}

const TONES: Record<SlotTone, string> = {
  selected: 'border-l-success bg-success-subtle text-success',
  open: 'border-l-accent bg-accent-subtle text-accent',
  pending: 'border-l-warning bg-warning-subtle text-warning',
  confirmed: 'border-l-success bg-success-subtle text-success',
  mine: 'border-l-info bg-info-subtle text-info',
  busy: 'border-l-fg-subtle bg-inset text-fg-subtle',
}

/** Couleurs de la croix de retrait, accordées au bloc qu'elle concerne. */
const CROSS_TONES: Record<SlotTone, string> = {
  selected: 'bg-success-subtle text-success',
  open: 'bg-accent-subtle text-accent',
  pending: 'bg-warning-subtle text-warning',
  confirmed: 'bg-success-subtle text-success',
  mine: 'bg-info-subtle text-info',
  busy: 'bg-inset text-fg-subtle',
}

export function SlotGrid({
  week,
  blocks,
  getCellState,
  selected,
  onGesture,
  onCellDelete,
  onBlockMove,
  selectionLabel,
}: SlotGridProps) {
  const rows = useMemo(() => buildSlotRows(), [])
  const [drag, setDrag] = useState<DragState | null>(null)
  const [move, setMove] = useState<MoveState | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const available = useElementWidth(scrollRef)

  /**
   * Colonnes en pixels entiers.
   *
   * Avec `1fr`, les sept colonnes tombent à des positions fractionnaires : une
   * bordure d'un pixel s'y étale sur deux pixels à opacité partielle, et
   * certaines colonnes paraissent dépourvues de séparateur. Arrondir la largeur
   * à l'entier inférieur rend les sept traits identiques.
   */
  const dayWidth = Math.max(
    MIN_DAY_COL_PX,
    Math.floor((Math.max(available, TIME_COL_PX + 7 * MIN_DAY_COL_PX) - TIME_COL_PX) / 7),
  )
  const template = `${TIME_COL_PX}px repeat(7, ${dayWidth}px)`
  const totalWidth = TIME_COL_PX + 7 * dayWidth

  /** Applique un tracé à une copie de la sélection, et note ce qui change. */
  const applyDrag = useCallback(
    (state: DragState, base: ReadonlySet<string>): GestureResult => {
      const [from, to] =
        state.anchor <= state.head ? [state.anchor, state.head] : [state.head, state.anchor]
      const day = week.days.find((candidate) => candidate.key === state.dayKey)
      const next = new Set(base)
      const added: string[] = []
      const removed: string[] = []
      if (!day) return { next, added, removed }

      for (let index = from; index <= to; index += 1) {
        const row = rows[index]
        if (!row) continue
        const key = slotKey(day, row)
        if (state.mode === 'remove') {
          if (next.delete(key)) removed.push(key)
        } else if (getCellState(day.key, index).selectable && !next.has(key)) {
          next.add(key)
          added.push(key)
        }
      }
      return { next, added, removed }
    },
    [week, rows, getCellState],
  )

  // Le geste doit se terminer même si le pointeur quitte la grille : sans
  // écouteur global, relâcher au-dessus de l'en-tête laissait le tracé figé.
  useEffect(() => {
    if (!drag) return
    const commit = () => {
      onGesture(applyDrag(drag, selected))
      setDrag(null)
    }
    window.addEventListener('pointerup', commit)
    window.addEventListener('pointercancel', commit)
    return () => {
      window.removeEventListener('pointerup', commit)
      window.removeEventListener('pointercancel', commit)
    }
  }, [drag, selected, applyDrag, onGesture])

  useEffect(() => {
    if (!move) return
    const commit = () => {
      const delta = move.head - move.grab
      if (delta !== 0) onBlockMove?.(move.block, delta)
      setMove(null)
    }
    window.addEventListener('pointerup', commit)
    window.addEventListener('pointercancel', commit)
    return () => {
      window.removeEventListener('pointerup', commit)
      window.removeEventListener('pointercancel', commit)
    }
  }, [move, onBlockMove])

  const onPointerDown = useCallback(
    (
      event: ReactPointerEvent<HTMLDivElement>,
      dayKey: string,
      index: number,
      block: SlotBlock | undefined,
    ) => {
      if (event.button !== 0) return
      const day = week.days.find((candidate) => candidate.key === dayKey)
      const row = rows[index]
      if (!day || !row) return

      // Saisir un créneau déjà posé le déplace ; saisir une case vide trace
      // une nouvelle sélection. Les deux gestes ne peuvent pas se confondre :
      // une case occupée n'est jamais sélectionnable.
      const state = getCellState(dayKey, index)
      if (block && block.slotIds.length > 0 && state.movable && onBlockMove) {
        event.preventDefault()
        setMove({ block, grab: index, head: index })
        return
      }

      const key = slotKey(day, row)
      const isSelected = selected.has(key)
      if (!isSelected && !state.selectable) return
      event.preventDefault()
      setDrag({ dayKey, anchor: index, head: index, mode: isSelected ? 'remove' : 'add' })
    },
    [week, rows, selected, getCellState, onBlockMove],
  )

  /**
   * Le survol passe par `elementFromPoint` plutôt que par `pointerenter` : en
   * tactile, le pointeur reste capturé par la case d'origine et aucune autre
   * ne reçoit d'événement d'entrée.
   */
  const onPointerMove = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      if (!drag && !move) return
      const cell = document
        .elementFromPoint(event.clientX, event.clientY)
        ?.closest<HTMLElement>('[data-slot-day]')
      if (!cell) return
      const index = Number(cell.dataset.slotIndex)
      if (!Number.isInteger(index)) return

      if (move) {
        // Le déplacement reste dans la colonne d'origine : changer de jour
        // demanderait de revalider tout le rendez-vous côté serveur, et ce
        // n'est pas ce qu'on cherche en décalant une réunion d'un quart d'heure.
        if (cell.dataset.slotDay !== move.block.dayKey || index === move.head) return
        setMove({ ...move, head: index })
        return
      }
      if (!drag || cell.dataset.slotDay !== drag.dayKey || index === drag.head) return
      setDrag({ ...drag, head: index })
    },
    [drag, move],
  )

  const preview = drag ? applyDrag(drag, selected).next : selected

  // Les quarts d'heure contigus fusionnent en un seul rectangle : répéter
  // « 09:00 – 09:15 » sur chaque ligne d'une plage d'une heure serait illisible.
  const { starts: byCell, covers: coverage } = useMemo(() => {
    const map = new Map<string, SlotBlock>()
    // Le bloc en cours de déplacement est affiché à sa position d'arrivée :
    // sans cet aperçu, on lâche à l'aveugle.
    const shift = move ? move.head - move.grab : 0
    for (const block of blocks) {
      const moving = move !== null && block.id === move.block.id
      const startIndex = moving ? block.startIndex + shift : block.startIndex
      map.set(`${block.dayKey}:${startIndex}`, moving ? { ...block, startIndex } : block)
    }

    for (const day of week.days) {
      let index = 0
      while (index < rows.length) {
        const row = rows[index]
        if (!row || !preview.has(slotKey(day, row))) {
          index += 1
          continue
        }
        let end = index
        while (end + 1 < rows.length) {
          const next = rows[end + 1]
          if (!next || !preview.has(slotKey(day, next))) break
          end += 1
        }
        const last = rows[end]
        // La sélection écrase un éventuel bloc serveur au même endroit.
        map.set(`${day.key}:${index}`, {
          id: `sel-${day.key}-${row.time}`,
          slotIds: [],
          dayKey: day.key,
          startIndex: index,
          length: end - index + 1,
          tone: 'selected',
          label: `${row.time} – ${last?.endTime ?? row.endTime}`,
          title: selectionLabel,
        })
        index = end + 1
      }
    }

    // Chaque case couverte par un bloc connaît le bloc dont elle relève : la
    // croix de suppression doit en reprendre les couleurs, et le glisser doit
    // pouvoir démarrer depuis n'importe quel quart d'heure du bloc.
    const covers = new Map<string, SlotBlock>()
    for (const [key, block] of map) {
      const [dayKey, startText] = key.split(':')
      const start = Number(startText)
      for (let offset = 0; offset < block.length; offset += 1) {
        covers.set(`${dayKey}:${start + offset}`, block)
      }
    }
    return { starts: map, covers }
  }, [blocks, week, rows, preview, selectionLabel, move])

  return (
    <div
      ref={scrollRef}
      onPointerMove={onPointerMove}
      // Bloquer le défilement tactile seulement pendant le tracé : le reste du
      // temps la grille doit rester parcourable au doigt.
      style={{ touchAction: drag ? 'none' : 'auto' }}
      // Un seul conteneur de défilement pour l'en-tête et le corps : deux
      // boîtes distinctes se décalaient de la largeur de la barre de
      // défilement, et les colonnes ne tombaient plus en face.
      className="h-full w-full overflow-auto rounded-[8px] border border-line bg-canvas"
    >
      <div style={{ width: totalWidth }}>
        <div
          className="sticky top-0 z-20 grid border-b-2 border-line bg-canvas"
          style={{ gridTemplateColumns: template }}
        >
          <div className="border-r border-line bg-canvas" />
          {week.days.map((day) => (
            <div
              key={day.iso}
              className={cn(
                'border-r border-line bg-canvas px-1 py-2.5 text-center text-[12px] font-semibold last:border-r-0',
                day.isToday ? 'text-accent' : 'text-fg-muted',
              )}
            >
              {day.name} {day.dayOfMonth}/{day.month}
            </div>
          ))}
        </div>

        <div className="grid" style={{ gridTemplateColumns: template }}>
          {rows.map((row, index) => (
            <div key={row.time} className="contents">
              <div
                style={{ height: SLOT_HEIGHT_PX }}
                className={cn(
                  'flex items-start justify-end border-r border-line bg-canvas pr-2 text-[11px] leading-none',
                  row.isHourMark ? 'pt-0.5 text-fg-muted' : 'text-transparent',
                )}
              >
                {row.isHourMark ? `${row.hour}:00` : ''}
              </div>

              {week.days.map((day) => {
                const key = slotKey(day, row)
                const state = getCellState(day.key, index)
                const block = byCell.get(`${day.key}:${index}`)
                const cover = coverage.get(`${day.key}:${index}`)
                const interactive = state.selectable || preview.has(key)
                const draggable = Boolean(state.movable && cover && onBlockMove)

                return (
                  <div
                    key={key}
                    data-slot-day={day.key}
                    data-slot-index={index}
                    role={interactive ? 'button' : undefined}
                    tabIndex={interactive ? 0 : -1}
                    aria-pressed={interactive ? preview.has(key) : undefined}
                    aria-label={`${day.name} ${row.time} à ${row.endTime}`}
                    onPointerDown={(event) => onPointerDown(event, day.key, index, cover)}
                    onKeyDown={(event) => {
                      if (!interactive || (event.key !== 'Enter' && event.key !== ' ')) return
                      event.preventDefault()
                      const next = new Set(selected)
                      const isSelected = next.has(key)
                      if (isSelected) next.delete(key)
                      else next.add(key)
                      onGesture({
                        next,
                        added: isSelected ? [] : [key],
                        removed: isSelected ? [key] : [],
                      })
                    }}
                    style={{ height: SLOT_HEIGHT_PX }}
                    className={cn(
                      'group/cell relative select-none border-r border-line last:border-r-0',
                      row.isHourMark && 'border-t border-t-line',
                      row.isHalfHour && 'border-t border-dashed border-t-line-subtle',
                      state.blocked
                        ? 'cursor-not-allowed bg-inset'
                        : draggable
                          ? 'cursor-grab bg-canvas active:cursor-grabbing'
                          : state.available
                            ? // Disponibilité offerte : teinte bleue franche, pour qu'on
                              // voie du premier coup d'œil où il est possible de cliquer.
                              'cursor-pointer bg-accent-subtle transition-colors hover:bg-accent/25'
                            : interactive
                              ? 'cursor-pointer bg-canvas transition-colors hover:bg-surface-hover'
                              : 'bg-canvas',
                    )}
                  >
                    {state.blocked ? (
                      <span
                        aria-hidden="true"
                        className="pointer-events-none absolute inset-0 opacity-40"
                        style={{
                          background:
                            'repeating-linear-gradient(-45deg, transparent, transparent 3px, var(--border-subtle) 3px, var(--border-subtle) 4px)',
                        }}
                      />
                    ) : null}

                    {block ? (
                      <span
                        title={block.title ?? block.label}
                        // Le bloc ne capte plus le clic : il laisse passer le
                        // geste vers la case, qui gère le déplacement, et la
                        // suppression passe par la croix.
                        className={cn(
                          'pointer-events-none absolute inset-y-0 left-0 right-px z-10 flex items-center justify-center',
                          'overflow-hidden rounded-[3px] border-l-[3px] px-1 text-[10px] font-semibold leading-tight',
                          TONES[block.tone],
                          move !== null && block.id === move.block.id && 'opacity-70 ring-1 ring-accent',
                        )}
                        style={{ height: block.length * SLOT_HEIGHT_PX - 1 }}
                      >
                        <span className="w-full truncate text-center">{block.label}</span>
                      </span>
                    ) : null}

                    {state.deletable && onCellDelete ? (
                      <button
                        type="button"
                        aria-label={`Retirer ${row.time}`}
                        title={`Retirer ${row.time} – ${row.endTime}`}
                        onPointerDown={(event) => event.stopPropagation()}
                        onClick={(event) => {
                          event.stopPropagation()
                          onCellDelete(day.key, index)
                        }}
                        className={cn(
                          // Invisible au repos : une croix sur chaque quart
                          // d'heure saturerait la grille.
                          'absolute right-0.5 top-1/2 z-20 hidden h-3.5 w-3.5 -translate-y-1/2',
                          'cursor-pointer items-center justify-center rounded-full border-none',
                          'text-[9px] font-bold leading-none group-hover/cell:flex',
                          // Mêmes couleurs que le bloc qu'elle retire.
                          cover ? CROSS_TONES[cover.tone] : 'bg-inset text-fg-muted',
                        )}
                      >
                        ✕
                      </button>
                    ) : null}
                  </div>
                )
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
