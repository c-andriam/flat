import { useCallback, useMemo, useState, type ReactNode } from 'react'

import type { ApiError } from '@/api/client'
import {
  useCancelSlotRequest,
  useDeleteSlot,
  useMoveSlots,
  useOpenSlots,
  useRequestSlots,
  useSlotOwners,
  useSlotRequests,
  useSlots,
  isOptimisticSlot,
} from '@/api/queries'
import type { Slot, SlotRequest } from '@/api/types'
import { useAuth } from '@/auth/useAuth'
import { SlotGrid, type GestureResult } from '@/features/slots/SlotGrid'
import {
  MIN_LEAD_MINUTES,
  buildSlotRows,
  formatDuration,
  isSlotDisabled,
  localDayIso,
  localTimeLabel,
  toMgIso,
  useWeek,
  type CellState,
  type SlotBlock,
  type WeekModel,
} from '@/features/slots/useWeek'
import { cn } from '@/lib/cn'
import { formatDateLong } from '@/lib/date'
import { Badge } from '@/ui/Badge'
import { Breadcrumb } from '@/ui/Breadcrumb'
import { Button } from '@/ui/Button'
import { EmptyState } from '@/ui/EmptyState'
import { ErrorState } from '@/ui/ErrorState'
import { SelectField, TextField } from '@/ui/Field'
import { IconCalendarPlus, IconChevronLeft, IconChevronRight, IconTrash } from '@/ui/Icon'
import { Modal } from '@/ui/Modal'
import { useToast } from '@/ui/useToast'

const ROWS = buildSlotRows()

/** Index `jour|heure` des créneaux renvoyés par l'API, pour un accès direct. */
function indexSlots(slots: Slot[]): Map<string, Slot> {
  const map = new Map<string, Slot>()
  for (const slot of slots) {
    map.set(`${localDayIso(slot.starts_at)}|${localTimeLabel(slot.starts_at)}`, slot)
  }
  return map
}

export function SlotsPage() {
  const toast = useToast()
  const { user } = useAuth()
  const [weekOffset, setWeekOffset] = useState(0)
  const [selection, setSelection] = useState<Record<string, ReadonlySet<string>>>({})
  const [requestModalOpen, setRequestModalOpen] = useState(false)
  const [subject, setSubject] = useState('')

  const week = useWeek(weekOffset)
  const weekId = week.days[0]?.iso ?? 'semaine'
  const selected = useMemo(() => selection[weekId] ?? new Set<string>(), [selection, weekId])
  const setSelected = useCallback(
    (next: ReadonlySet<string>) => setSelection((current) => ({ ...current, [weekId]: next })),
    [weekId],
  )
  const clear = useCallback(() => setSelected(new Set<string>()), [setSelected])

  /**
   * Seul le DSIO ouvre des disponibilités et arbitre les demandes.
   *
   * `admin` en est exclu : c'est un rôle d'administration des comptes, pas un
   * interlocuteur. L'inclure lui donnait un agenda de rendez-vous et la
   * lecture de l'objet des entretiens du DSIO.
   */
  const canOwnSlots = user?.role === 'dsio'

  const ownersQuery = useSlotOwners()

  /**
   * L'agenda regardé est celui d'un propriétaire précis, jamais « le mien »
   * implicitement : un admin qui consultait automatiquement son propre
   * identifiant ne voyait jamais les disponibilités du DSIO, et
   * réciproquement. Le compte courant n'apparaît dans la liste que s'il peut
   * lui-même ouvrir des créneaux.
   */
  const owners = useMemo(() => {
    const list = (ownersQuery.data ?? []).map((owner) => ({
      id: owner.id,
      label: owner.display_name,
    }))
    return list
  }, [ownersQuery.data])

  const [ownerChoice, setOwnerChoice] = useState('')

  /**
   * Le DSIO arrive sur son propre agenda ; tout autre compte sur celui du
   * premier DSIO. Faire pointer un compte vers son propre identifiant lui
   * montrait un agenda vide, en lui laissant croire que le DSIO n'avait rien
   * ouvert.
   */
  const defaultOwnerId = canOwnSlots && user ? user.id : (owners[0]?.id ?? '')

  const effectiveOwnerId = owners.some((owner) => owner.id === ownerChoice)
    ? ownerChoice
    : defaultOwnerId

  /** On ne peut modifier que son propre agenda. */
  const canEdit = canOwnSlots && effectiveOwnerId === user?.id

  const firstDay = week.days[0]?.iso ?? ''
  const lastDay = week.days[6]?.iso ?? ''

  /**
   * La fenêtre est demandée sans `owner_id`, et le filtrage par propriétaire
   * se fait côté client.
   *
   * Filtrer côté serveur imposait d'attendre `/auth/me`, puis `/slots/owners`,
   * puis seulement `/slots` : trois allers-retours en file indienne, soit
   * plusieurs secondes avant le premier affichage sur une base distante. Les
   * trois appels partent maintenant en parallèle.
   */
  const slotsQuery = useSlots(
    { from: toMgIso(firstDay, '00:00'), to: toMgIso(lastDay, '23:59') },
    Boolean(firstDay),
  )
  const requestsQuery = useSlotRequests({ upcoming_only: true })

  const openSlots = useOpenSlots()
  const deleteSlot = useDeleteSlot()
  const requestSlots = useRequestSlots()
  const moveSlots = useMoveSlots()
  const cancelRequest = useCancelSlotRequest()

  const slotsByCell = useMemo(
    () =>
      indexSlots(
        (slotsQuery.data ?? []).filter(
          (slot) => !effectiveOwnerId || slot.owner_user_id === effectiveOwnerId,
        ),
      ),
    [slotsQuery.data, effectiveOwnerId],
  )

  const slotAt = useCallback(
    (dayKey: string, rowIndex: number): Slot | undefined => {
      const day = week.days.find((candidate) => candidate.key === dayKey)
      const row = ROWS[rowIndex]
      if (!day || !row) return undefined
      return slotsByCell.get(`${day.iso}|${row.time}`)
    },
    [week, slotsByCell],
  )

  /**
   * Sur son propre agenda, une case est ouvrable si elle respecte les horaires
   * et n'est pas déjà ouverte. Sur celui d'un autre, elle n'est sélectionnable
   * que si une disponibilité libre y existe : on ne réserve pas du vide.
   */
  const getCellState = useCallback(
    (dayKey: string, rowIndex: number): CellState => {
      const day = week.days.find((candidate) => candidate.key === dayKey)
      const row = ROWS[rowIndex]
      if (!day || !row) return { selectable: false, blocked: true }

      const slot = slotAt(dayKey, rowIndex)
      const outOfRules = isSlotDisabled(day, row, week)

      if (canEdit) {
        // Sur son propre agenda, un créneau déjà posé reste manipulable même
        // si l'heure est sortie des règles entre-temps : on doit pouvoir le
        // déplacer ou le retirer, pas seulement le subir.
        if (slot) {
          // Un créneau posé à l'instant n'a pas encore d'identifiant serveur :
          // le déplacer ou le retirer produirait un 404. L'attente se compte
          // en dizaines de millisecondes, elle est invisible.
          const confirme = !isOptimisticSlot(slot)
          return {
            selectable: false,
            blocked: false,
            deletable: confirme,
            movable: confirme,
          }
        }
        return { selectable: !outOfRules, blocked: outOfRules }
      }

      if (outOfRules || !slot) return { selectable: false, blocked: true }
      if (slot.status === 'open') {
        return { selectable: true, blocked: false, available: true }
      }
      // Un rendez-vous que l'on a soi-même pris peut être annulé d'ici.
      return {
        selectable: false,
        blocked: false,
        deletable: slot.is_mine && !isOptimisticSlot(slot),
      }
    },
    [week, canEdit, slotAt],
  )

  /** Blocs serveur : disponibilités ouvertes et rendez-vous, fusionnés. */
  const blocks = useMemo<SlotBlock[]>(() => {
    const result: SlotBlock[] = []
    for (const day of week.days) {
      let index = 0
      while (index < ROWS.length) {
        const row = ROWS[index]
        const slot = row ? slotsByCell.get(`${day.iso}|${row.time}`) : undefined
        if (!row || !slot) {
          index += 1
          continue
        }
        // Regroupement : même statut et même rendez-vous. Deux créneaux libres
        // adjacents fusionnent, deux rendez-vous distincts non.
        const members: Slot[] = [slot]
        let end = index
        while (end + 1 < ROWS.length) {
          const nextRow = ROWS[end + 1]
          const nextSlot = nextRow ? slotsByCell.get(`${day.iso}|${nextRow.time}`) : undefined
          if (
            !nextSlot ||
            nextSlot.status !== slot.status ||
            nextSlot.request_group_id !== slot.request_group_id
          ) {
            break
          }
          members.push(nextSlot)
          end += 1
        }

        const lastRow = ROWS[end]
        const range = `${row.time} – ${lastRow?.endTime ?? row.endTime}`
        const slotIds = members.map((member) => member.id)

        if (slot.status === 'open') {
          // Une disponibilité libre n'est signalée par un bloc que sur son
          // propre agenda : ailleurs, la case cliquable suffit et un bloc
          // masquerait inutilement la grille.
          if (canEdit) {
            result.push({
              id: slot.id,
              slotIds,
              dayKey: day.key,
              startIndex: index,
              length: end - index + 1,
              tone: 'open',
              label: range,
              title: `Disponibilité ouverte ${range} — cliquer pour la retirer`,
              actionable: true,
            })
          }
        } else {
          const who = slot.requested_by_display_name
          const visible = canOwnSlots || slot.is_mine
          const tone = slot.is_mine ? 'mine' : 'confirmed'
          result.push({
            id: slot.request_group_id ?? slot.id,
            slotIds,
            dayKey: day.key,
            startIndex: index,
            length: end - index + 1,
            tone: visible ? tone : 'busy',
            label: visible ? (who ?? 'Réservé') : 'Réservé',
            title: `${range}${who && visible ? ` · ${who}` : ''}${slot.subject && visible ? ` · ${slot.subject}` : ''}`,
          })
        }
        index = end + 1
      }
    }
    return result
  }, [week, slotsByCell, canEdit, canOwnSlots])

  /**
   * Fin d'un geste — clic simple ou tracé.
   *
   * Sur son propre agenda, l'ouverture est immédiate : le geste *est* la
   * validation, il n'y a pas de bouton à confirmer derrière. Sur celui d'un
   * autre, le geste ne fait que constituer la sélection ; l'objet du
   * rendez-vous reste à saisir avant l'envoi.
   */
  const onGesture = useCallback(
    ({ next, added }: GestureResult) => {
      if (!canEdit) {
        setSelected(next)
        // Le geste vaut demande : la sélection enchaîne directement sur la
        // saisie du motif, sans bouton « Demander » à retrouver ailleurs.
        if (next.size > 0) setRequestModalOpen(true)
        return
      }
      if (added.length === 0) return

      const starts = added
        .map((key) => {
          const [dayKey, time] = key.split('_')
          const day = week.days.find((candidate) => candidate.key === dayKey)
          return day && time ? toMgIso(day.iso, time) : null
        })
        .filter((value): value is string => value !== null)
        .sort()

      if (starts.length === 0) return
      if (!user) return
      openSlots.mutate(
        { starts_at: starts, owner: { id: user.id, display_name: user.display_name } },
        { onError: (error: ApiError) => toast.error(error.message) },
      )
    },
    [canEdit, setSelected, week, openSlots, toast, user],
  )

  /**
   * Croix de retrait, un quart d'heure à la fois.
   *
   * Sur un créneau libre, seule la case cliquée disparaît. Sur un rendez-vous,
   * c'est le rendez-vous entier qui est annulé : en amputer un quart d'heure
   * laisserait une réunion tronquée que personne n'a acceptée.
   */
  const removeCell = useCallback(
    (dayKey: string, rowIndex: number) => {
      const day = week.days.find((candidate) => candidate.key === dayKey)
      const row = ROWS[rowIndex]
      if (!day || !row) return
      const slot = slotsByCell.get(`${day.iso}|${row.time}`)
      if (!slot) return

      if (slot.status === 'confirmed' && slot.request_group_id) {
        cancelRequest.mutate(slot.request_group_id, {
          onSuccess: () => toast.info('Rendez-vous annulé, créneaux réouverts.'),
          onError: (error: ApiError) => toast.error(error.message),
        })
        return
      }
      deleteSlot.mutate(slot.id, {
        onError: (error: ApiError) => toast.error(error.message),
      })
    },
    [week, slotsByCell, cancelRequest, deleteSlot, toast],
  )

  /** Déplacement d'un bloc, exprimé en quarts d'heure. */
  const moveBlock = useCallback(
    (block: SlotBlock, deltaRows: number) => {
      const day = week.days.find((candidate) => candidate.key === block.dayKey)
      const target = ROWS[block.startIndex + deltaRows]
      if (!day || !target || block.slotIds.length === 0) return
      moveSlots.mutate(
        { slot_ids: block.slotIds, starts_at: toMgIso(day.iso, target.time) },
        { onError: (error: ApiError) => toast.error(error.message) },
      )
    },
    [week, moveSlots, toast],
  )

  /** Horodatages ISO des cases sélectionnées, triés. */
  const selectedIso = useMemo(() => {
    const out: string[] = []
    for (const key of selected) {
      const [dayKey, time] = key.split('_')
      const day = week.days.find((candidate) => candidate.key === dayKey)
      if (!day || !time) continue
      out.push(toMgIso(day.iso, time))
    }
    return out.sort()
  }, [selected, week])

  /** Identifiants des créneaux sélectionnés, pour une demande. */
  const selectedSlotIds = useMemo(() => {
    const out: string[] = []
    for (const key of selected) {
      const [dayKey, time] = key.split('_')
      const day = week.days.find((candidate) => candidate.key === dayKey)
      if (!day || !time) continue
      const slot = slotsByCell.get(`${day.iso}|${time}`)
      if (slot) out.push(slot.id)
    }
    return out
  }, [selected, week, slotsByCell])

  const submitRequest = () => {
    if (!user) return
    // La modale se ferme sans attendre : la grille montre déjà le rendez-vous,
    // et un échec le retirera en affichant l'erreur.
    const slotIds = selectedSlotIds
    const motif = subject.trim() || null
    setRequestModalOpen(false)
    setSubject('')
    clear()
    requestSlots.mutate(
      {
        slot_ids: slotIds,
        subject: motif,
        requester: { id: user.id, display_name: user.display_name },
      },
      { onError: (error: ApiError) => toast.error(error.message) },
    )
  }

  // Il n'y a plus qu'un état : le rendez-vous est confirmé dès qu'il est pris.
  const requests = requestsQuery.data ?? []

  return (
    <div
      // Hauteur fixée sur grand écran : la page tient d'un bloc, seules la
      // grille et le panneau latéral défilent. Sous `lg`, sept colonnes ne
      // tiennent de toute façon pas dans la fenêtre et le défilement de page
      // reprend ses droits.
      className="flex flex-col lg:h-[calc(100dvh-14.5rem)] lg:min-h-[26rem] lg:overflow-hidden"
    >
      <div className="shrink-0">
        <Breadcrumb
          items={[{ label: "Vue d'ensemble", to: '/tableau-de-bord' }, { label: 'Créneaux' }]}
        />

        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-2xl font-semibold tracking-[-0.01em] text-fg">Créneaux</h2>
            <p className="mt-1 max-w-[70ch] text-[13px] leading-relaxed text-fg-muted">
              {canEdit
                ? `Un clic ouvre 15 minutes, un cliquer-glisser ouvre une plage — l'enregistrement est immédiat. Glissez un créneau posé pour le décaler, et survolez une case pour faire apparaître la croix de retrait. Aucun créneau ne peut commencer dans moins de ${MIN_LEAD_MINUTES} minutes.`
                : `Cliquez un créneau bleu — ou glissez sur plusieurs quarts d'heure consécutifs — pour prendre rendez-vous. Il ne reste qu'à indiquer le motif : le rendez-vous est confirmé immédiatement.`}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {owners.length > 1 ? (
              <SelectField
                className="w-56"
                aria-label="Agenda consulté"
                value={effectiveOwnerId}
                onChange={(event) => {
                  setOwnerChoice(event.target.value)
                  clear()
                }}
                options={owners.map((owner) => ({ value: owner.id, label: owner.label }))}
              />
            ) : null}
          </div>
        </div>

        <WeekNavigator week={week} onOffsetChange={setWeekOffset} />
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-4 xl:flex-row">
        <div className="flex min-h-0 flex-1 flex-col gap-2">
          {owners.length === 0 && !ownersQuery.isLoading ? (
            <EmptyState
              icon={<IconCalendarPlus size={44} strokeWidth={1.5} />}
              title="Aucun interlocuteur disponible"
              message="Aucun compte DSIO n'est encore configuré : personne ne peut ouvrir de créneaux pour l'instant."
            />
          ) : slotsQuery.isError ? (
            <ErrorState error={slotsQuery.error} onRetry={() => void slotsQuery.refetch()} />
          ) : (
            <>
              <div className="min-h-0 flex-1">
                <SlotGrid
                  week={week}
                  blocks={blocks}
                  getCellState={getCellState}
                  selected={selected}
                  onGesture={onGesture}
                  onCellDelete={removeCell}
                  onBlockMove={canEdit ? moveBlock : undefined}
                  selectionLabel={canEdit ? 'Nouvelle disponibilité' : 'Rendez-vous demandé'}
                />
              </div>
              <Legend canEdit={canEdit} />
            </>
          )}
        </div>

        <aside className="flex min-h-0 w-full flex-col gap-4 overflow-y-auto xl:w-[340px] xl:shrink-0">
          <RequestList
            title={canOwnSlots ? 'Rendez-vous à venir' : 'Mes rendez-vous'}
            requests={requests}
            loading={requestsQuery.isLoading}
            emptyLabel={
              canOwnSlots ? 'Aucun rendez-vous à venir.' : "Vous n'avez aucun rendez-vous."
            }
            renderActions={(item) => (
              <Button
                size="sm"
                variant="danger"
                onClick={() =>
                  cancelRequest.mutate(item.request_group_id, {
                    onSuccess: () => toast.info('Rendez-vous annulé.'),
                    onError: (error: ApiError) => toast.error(error.message),
                  })
                }
              >
                <IconTrash size={13} />
                Annuler
              </Button>
            )}
          />
        </aside>
      </div>

      <Modal
        open={requestModalOpen}
        onClose={() => {
          setRequestModalOpen(false)
          clear()
        }}
        title="Confirmer le rendez-vous"
        footer={
          <>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                setRequestModalOpen(false)
                clear()
              }}
            >
              Annuler
            </Button>
            <Button
              size="sm"
              variant="primary"
              loading={requestSlots.isPending}
              onClick={submitRequest}
            >
              Confirmer
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          {selectedIso.length > 0 ? (
            <p className="text-[13px] leading-relaxed text-fg-muted">
              {formatDateLong(selectedIso[0]?.slice(0, 10))} ·{' '}
              <span className="font-semibold text-fg">
                {selectedIso[0]?.slice(11, 16)} — {formatDuration(selected.size)}
              </span>
            </p>
          ) : null}
          <TextField
            label="Objet du rendez-vous"
            placeholder="Ex : Arbitrage budget 2027"
            hint="Visible du DSIO uniquement."
            value={subject}
            onChange={(event) => setSubject(event.target.value)}
          />
        </div>
      </Modal>
    </div>
  )
}

function WeekNavigator({
  week,
  onOffsetChange,
}: {
  week: WeekModel
  onOffsetChange: (updater: (offset: number) => number) => void
}) {
  return (
    <div className="mb-3 flex flex-wrap items-center justify-center gap-3 sm:gap-5">
      <span className="text-lg font-normal tracking-[-0.01em] text-accent">{week.label}</span>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => onOffsetChange(() => 0)}
          className="cursor-pointer rounded-[4px] border-none bg-accent px-4 py-1.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-85"
        >
          Aujourd'hui
        </button>
        <button
          type="button"
          onClick={() => onOffsetChange((offset) => offset - 1)}
          aria-label="Semaine précédente"
          className="flex h-[30px] w-[30px] cursor-pointer items-center justify-center rounded-[4px] border border-line bg-surface text-fg-muted transition-colors hover:bg-surface-hover hover:text-fg"
        >
          <IconChevronLeft size={17} />
        </button>
        <button
          type="button"
          onClick={() => onOffsetChange((offset) => offset + 1)}
          aria-label="Semaine suivante"
          className="flex h-[30px] w-[30px] cursor-pointer items-center justify-center rounded-[4px] border border-line bg-surface text-fg-muted transition-colors hover:bg-surface-hover hover:text-fg"
        >
          <IconChevronRight size={17} />
        </button>
      </div>
    </div>
  )
}

function Legend({ canEdit }: { canEdit: boolean }) {
  const items = canEdit
    ? [
        { className: 'border-l-accent bg-accent-subtle', label: 'Disponibilité ouverte' },
        { className: 'border-l-success bg-success-subtle', label: 'Rendez-vous' },
        { className: 'bg-canvas', label: 'Libre — cliquer pour ouvrir' },
        { className: 'bg-inset', label: 'Indisponible' },
      ]
    : [
        { className: 'bg-accent-subtle border-accent', label: 'Disponible — cliquer' },
        { className: 'border-l-info bg-info-subtle', label: 'Mon rendez-vous' },
        { className: 'border-l-fg-subtle bg-inset', label: 'Déjà réservé' },
        { className: 'bg-inset', label: 'Indisponible' },
      ]

  return (
    <div className="flex shrink-0 flex-wrap gap-4 text-[11px] text-fg-muted">
      {items.map((item) => (
        <span key={item.label} className="flex items-center gap-1.5">
          <span
            className={cn(
              'h-3.5 w-3.5 rounded-[3px] border border-l-[3px] border-line',
              item.className,
            )}
          />
          {item.label}
        </span>
      ))}
      <span className="ml-auto hidden lg:inline">
        {canEdit
          ? 'Clic = 15 min · glisser = plage · glisser un créneau = déplacer'
          : 'Clic = 15 min · glisser = plage'}
      </span>
    </div>
  )
}

function RequestList({
  title,
  requests,
  loading,
  emptyLabel,
  renderActions,
}: {
  title: string
  requests: SlotRequest[]
  loading: boolean
  emptyLabel: string
  renderActions: (item: SlotRequest) => ReactNode
}) {
  return (
    <section className="shrink-0 rounded-[8px] border border-line bg-surface">
      <h3 className="border-b border-line px-4 py-2.5 text-[13px] font-semibold text-fg">
        {title}
        {requests.length > 0 ? (
          <span className="ml-2 rounded-full bg-accent-subtle px-1.5 py-px text-[11px] font-semibold text-accent">
            {requests.length}
          </span>
        ) : null}
      </h3>
      <div className="flex flex-col gap-2 p-3">
        {loading ? (
          <p className="py-4 text-center text-[12px] text-fg-subtle">Chargement…</p>
        ) : requests.length === 0 ? (
          <p className="py-4 text-center text-[12px] text-fg-subtle">{emptyLabel}</p>
        ) : (
          requests.map((item) => (
            <article
              key={item.request_group_id}
              className="rounded-[6px] border border-line bg-canvas p-2.5"
            >
              <div className="mb-1.5 flex flex-wrap items-center gap-2">
                <span className="text-[12px] font-semibold text-fg">
                  {formatDateLong(localDayIso(item.starts_at))}
                </span>
                <Badge tone="green">
                  {localTimeLabel(item.starts_at)} – {localTimeLabel(item.ends_at)}
                </Badge>
              </div>
              <p className="mb-2 truncate text-[12px] text-fg-muted">
                {item.requested_by_display_name ?? item.owner_display_name}
                {item.subject ? ` · ${item.subject}` : ''}
              </p>
              <div className="flex flex-wrap gap-2">{renderActions(item)}</div>
            </article>
          ))
        )}
      </div>
    </section>
  )
}
