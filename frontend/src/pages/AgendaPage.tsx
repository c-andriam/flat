import { useCallback, useMemo, useState } from 'react'

import { useActions } from '@/api/queries'
import { useAuth } from '@/auth/useAuth'
import type { Action } from '@/api/types'
import { MonthCalendar, type DayMarker } from '@/features/agenda/MonthCalendar'
import { useMonthGrid } from '@/features/agenda/useMonthGrid'
import { ActionStatusBadge } from '@/features/actions/ActionStatusBadge'
import { addMonths, formatDateLong, monthNameFr, todayMg } from '@/lib/date'
import { holidayFor } from '@/lib/holidays'
import { cn } from '@/lib/cn'
import { Badge } from '@/ui/Badge'
import { Breadcrumb } from '@/ui/Breadcrumb'
import { Button } from '@/ui/Button'
import { EmptyState } from '@/ui/EmptyState'
import { ErrorState } from '@/ui/ErrorState'
import { IconBell, IconCalendar, IconChevronLeft, IconChevronRight } from '@/ui/Icon'
import { PageHeader } from '@/ui/PageHeader'
import { Skeleton } from '@/ui/Skeleton'

export function AgendaPage() {
  const { linkedResponsableIds } = useAuth()
  const today = todayMg()
  const [cursor, setCursor] = useState({
    year: today.getUTCFullYear(),
    month: today.getUTCMonth() + 1,
  })
  const [selectedDate, setSelectedDate] = useState<string | null>(null)

  const weeks = useMonthGrid(cursor.year, cursor.month)

  // Toutes les actions à échéance : le filtrage par mois se fait côté client,
  // la fenêtre affichée changeant plus vite qu'un aller-retour réseau.
  const actionsQuery = useActions({ view: 'open', limit: 500, active_projects_only: true })
  // Stabilisé : `data?.items ?? []` produirait un nouveau tableau à chaque
  // rendu, ce qui relancerait tous les regroupements ci-dessous pour rien.
  const actionsItems = actionsQuery.data?.items
  const actions = useMemo(() => actionsItems ?? [], [actionsItems])

  /**
   * Une action que porte le compte connecté.
   *
   * Un compte qui voit tout le portefeuille — DSIO, administrateur — a besoin
   * de retrouver ses propres échéances au milieu de celles des autres : ce
   * sont elles qui doivent ressortir, pas la première du jour.
   */
  const isMine = useCallback(
    (action: Action) =>
      action.responsables.some((responsable) => linkedResponsableIds.has(responsable.id)),
    [linkedResponsableIds],
  )

  const actionsByDate = useMemo(() => {
    const map = new Map<string, Action[]>()
    for (const action of actions) {
      if (!action.deadline) continue
      const bucket = map.get(action.deadline)
      if (bucket) bucket.push(action)
      else map.set(action.deadline, [action])
    }
    // Les siennes en tête de chaque journée : sur quatre échéances du jour,
    // c'est la sienne qu'on doit lire en premier.
    for (const bucket of map.values()) {
      bucket.sort((a, b) => Number(isMine(b)) - Number(isMine(a)))
    }
    return map
  }, [actions, isMine])

  const markersByDate = useMemo(() => {
    const map = new Map<string, DayMarker[]>()
    for (const [date, list] of actionsByDate) {
      const miennes = list.filter(isMine)
      const overdue = list.some((action) => action.status === 'en_retard')
      const blocked = list.some((action) => action.status === 'bloque')
      const marqueurs: DayMarker[] = []

      // Une pastille dédiée quand le jour porte une de ses échéances : elle
      // reste lisible même noyée dans le volume des autres.
      if (miennes.length > 0) {
        const premiere = miennes[0]
        marqueurs.push({
          label:
            miennes.length === 1 && premiere
              ? premiere.numero
              : `${miennes.length} à moi`,
          tone: 'mine',
          title: miennes
            .map((action) => `${action.numero} — ${action.description}`)
            .join('\n'),
        })
      }

      const autres = list.length - miennes.length
      if (autres > 0) {
        marqueurs.push({
          label: `${autres} autre${autres > 1 ? 's' : ''}`,
          tone: blocked ? 'danger' : overdue ? 'warning' : 'accent',
          title: list
            .filter((action) => !isMine(action))
            .map((action) => `${action.numero} — ${action.description}`)
            .join('\n'),
        })
      }
      map.set(date, marqueurs)
    }
    return map
  }, [actionsByDate, isMine])

  const goToday = () => {
    setCursor({ year: today.getUTCFullYear(), month: today.getUTCMonth() + 1 })
    setSelectedDate(null)
  }

  const shift = (delta: number) => {
    setCursor((current) => addMonths(current.year, current.month, delta))
    setSelectedDate(null)
  }

  const selectedActions = selectedDate ? (actionsByDate.get(selectedDate) ?? []) : []
  const upcoming = useMemo(
    () =>
      actions
        .filter((action) => action.deadline !== null)
        .sort(
          (a, b) =>
            Number(isMine(b)) - Number(isMine(a)) ||
            (a.deadline ?? '').localeCompare(b.deadline ?? ''),
        )
        .slice(0, 6),
    [actions, isMine],
  )

  return (
    <>
      <Breadcrumb items={[{ label: "Vue d'ensemble", to: '/tableau-de-bord' }, { label: 'Agenda' }]} />
      <PageHeader
        title="Agenda"
        description="Échéances des actions ouvertes et jours fériés malgaches."
      />

      <div className="flex flex-col items-start gap-6 lg:h-[calc(100dvh-260px)] lg:flex-row">
        {/* Calendrier */}
        <div className="flex h-full w-full min-w-0 flex-1 flex-col">
          <div className="mb-3 flex flex-wrap items-center gap-4">
            <Button size="sm" variant="secondary" onClick={goToday}>
              Aujourd'hui
            </Button>
            <div className="flex gap-1">
              <button
                type="button"
                onClick={() => shift(-1)}
                aria-label="Mois précédent"
                className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-full border-none bg-transparent text-fg-muted transition-colors hover:bg-surface-hover hover:text-fg"
              >
                <IconChevronLeft size={20} />
              </button>
              <button
                type="button"
                onClick={() => shift(1)}
                aria-label="Mois suivant"
                className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-full border-none bg-transparent text-fg-muted transition-colors hover:bg-surface-hover hover:text-fg"
              >
                <IconChevronRight size={20} />
              </button>
            </div>
            <h3 className="text-[22px] font-normal text-fg">
              {monthNameFr(cursor.month)} {cursor.year}
            </h3>
          </div>

          <MonthCalendar
            weeks={weeks}
            markersByDate={markersByDate}
            onSelectDay={setSelectedDate}
            selectedDate={selectedDate}
          />
        </div>

        {/* Panneau latéral */}
        <aside className="flex h-full w-full shrink-0 flex-col gap-6 lg:w-80">
          <section className="flex min-h-0 flex-1 flex-col">
            <h4 className="mb-3 flex items-center gap-2 text-[12px] font-semibold uppercase tracking-[0.05em] text-fg-muted">
              <IconCalendar size={14} />
              {selectedDate ? formatDateLong(selectedDate) : 'Prochaines échéances'}
            </h4>

            {selectedDate && holidayFor(selectedDate) ? (
              <p className="mb-3 rounded-[8px] border border-success/25 bg-success-subtle px-3 py-2 text-[13px] font-semibold text-success">
                {holidayFor(selectedDate)}
              </p>
            ) : null}

            <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto pb-4">
              {actionsQuery.isLoading ? (
                Array.from({ length: 3 }, (_, index) => (
                  <Skeleton key={index} className="h-20 w-full rounded-[8px]" />
                ))
              ) : actionsQuery.isError ? (
                <ErrorState error={actionsQuery.error} onRetry={() => void actionsQuery.refetch()} />
              ) : (selectedDate ? selectedActions : upcoming).length === 0 ? (
                <EmptyState
                  icon={<IconBell size={36} strokeWidth={1.5} />}
                  title={selectedDate ? 'Rien ce jour-là' : 'Aucune échéance'}
                  message={
                    selectedDate
                      ? 'Aucune action ouverte ne tombe à cette date.'
                      : 'Aucune action ouverte ne porte de date cible.'
                  }
                />
              ) : (
                (selectedDate ? selectedActions : upcoming).map((action) => (
                  <article
                    key={action.id}
                    className={cn(
                      'rounded-[8px] border bg-canvas p-4 transition-shadow hover:shadow-raised',
                      isMine(action)
                        ? 'border-info/50 ring-1 ring-info/25'
                        : 'border-line',
                    )}
                  >
                    <div className="mb-2 flex items-start justify-between gap-2">
                      <span className="flex items-center gap-2">
                        <span className="text-[12px] font-bold text-accent">{action.numero}</span>
                        {isMine(action) ? <Badge tone="purple">Moi</Badge> : null}
                      </span>
                      <ActionStatusBadge status={action.status} />
                    </div>
                    <p className="mb-2 line-clamp-2 text-sm font-medium leading-snug text-fg">
                      {action.description}
                    </p>
                    <p className="text-[12px] text-fg-subtle">
                      {formatDateLong(action.deadline)}
                      {action.resp_suivi ? ` · ${action.resp_suivi}` : ''}
                    </p>
                  </article>
                ))
              )}
            </div>
          </section>

          {selectedDate ? (
            <Button size="sm" variant="ghost" onClick={() => setSelectedDate(null)}>
              Afficher les prochaines échéances
            </Button>
          ) : null}
        </aside>
      </div>
    </>
  )
}
