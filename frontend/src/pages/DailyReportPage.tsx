import { useEffect, useMemo, useState, type FormEvent } from 'react'

import type { ApiError } from '@/api/client'
import { useSaveDailyReport, useSubmitDailyReport, useTodayReport } from '@/api/queries'
import type { ReportItemPayload, ReportSuggestion, TodayReport } from '@/api/types'
import { useDailyReminder } from '@/hooks/useDailyReminder'
import { cn } from '@/lib/cn'
import { formatDateLong } from '@/lib/date'
import { Badge, type BadgeTone } from '@/ui/Badge'
import { Breadcrumb } from '@/ui/Breadcrumb'
import { Button } from '@/ui/Button'
import { Card, CardBody, CardHeader } from '@/ui/Card'
import { EmptyState } from '@/ui/EmptyState'
import { ErrorState } from '@/ui/ErrorState'
import { TextAreaField, TextField } from '@/ui/Field'
import { IconCheck, IconCheckCircle, IconClipboard, IconPlus, IconTrash } from '@/ui/Icon'
import { PageHeader } from '@/ui/PageHeader'
import { Skeleton } from '@/ui/Skeleton'
import { useToast } from '@/ui/useToast'

/** Ligne telle qu'elle vit à l'écran, avant enregistrement. */
interface DraftItem {
  /** Clé locale : une ligne juste ajoutée n'a pas encore d'identifiant serveur. */
  key: string
  actionId: string | null
  label: string
  done: boolean
}

const REASON_TONES: Record<string, BadgeTone> = {
  deadline_today: 'orange',
  touched_today: 'blue',
  carry_over: 'neutral',
}

function toDraft(data: TodayReport | undefined): DraftItem[] {
  return (data?.report?.items ?? []).map((item) => ({
    key: item.id,
    actionId: item.action_id,
    label: item.label,
    done: item.done,
  }))
}

export function DailyReportPage() {
  const toast = useToast()
  const todayQuery = useTodayReport()
  const saveReport = useSaveDailyReport()
  const submitReport = useSubmitDailyReport()

  const [items, setItems] = useState<DraftItem[]>([])
  const [note, setNote] = useState('')
  const [nouveau, setNouveau] = useState('')
  const [charge, setCharge] = useState(false)

  const data = todayQuery.data
  const day = data?.report_date ?? ''

  // Le brouillon n'est initialisé qu'une fois : recopier la réponse serveur à
  // chaque rafraîchissement effacerait ce que l'utilisateur est en train
  // d'écrire.
  useEffect(() => {
    if (charge || !data) return
    setItems(toDraft(data))
    setNote(data.report?.note ?? '')
    setCharge(true)
  }, [data, charge])

  const { ignoredCount } = useDailyReminder(items.length > 0 || note.trim().length > 0)

  const dejaReprises = useMemo(
    () => new Set(items.map((item) => item.actionId).filter(Boolean)),
    [items],
  )
  const suggestions = (data?.suggestions ?? []).filter(
    (suggestion) => !dejaReprises.has(suggestion.action_id),
  )

  const enregistrer = (prochains: DraftItem[], prochaineNote: string) => {
    if (!day) return
    const payload: ReportItemPayload[] = prochains.map((item) => ({
      action_id: item.actionId,
      label: item.label,
      done: item.done,
    }))
    saveReport.mutate(
      { day, payload: { items: payload, note: prochaineNote.trim() || null } },
      { onError: (error: ApiError) => toast.error(error.message) },
    )
  }

  const ajouterSuggestion = (suggestion: ReportSuggestion, done: boolean) => {
    const prochains = [
      ...items,
      {
        key: `s-${suggestion.action_id}`,
        actionId: suggestion.action_id,
        label: `${suggestion.numero} — ${suggestion.description}`,
        done,
      },
    ]
    setItems(prochains)
    enregistrer(prochains, note)
  }

  const ajouterManuelle = (event: FormEvent) => {
    event.preventDefault()
    const libelle = nouveau.trim()
    if (!libelle) return
    const prochains = [
      ...items,
      { key: `m-${crypto.randomUUID()}`, actionId: null, label: libelle, done: true },
    ]
    setItems(prochains)
    setNouveau('')
    enregistrer(prochains, note)
  }

  const basculer = (key: string) => {
    const prochains = items.map((item) =>
      item.key === key ? { ...item, done: !item.done } : item,
    )
    setItems(prochains)
    enregistrer(prochains, note)
  }

  const retirer = (key: string) => {
    const prochains = items.filter((item) => item.key !== key)
    setItems(prochains)
    enregistrer(prochains, note)
  }

  const clore = () => {
    if (!day) return
    enregistrer(items, note)
    submitReport.mutate(day, {
      onSuccess: () => toast.success('Rapport de la journée enregistré.'),
      onError: (error: ApiError) => toast.error(error.message),
    })
  }

  const soumis = data?.report?.submitted_at ?? null

  if (todayQuery.isError) {
    return (
      <>
        <Breadcrumb
          items={[{ label: "Vue d'ensemble", to: '/tableau-de-bord' }, { label: 'Rapport du jour' }]}
        />
        <ErrorState error={todayQuery.error} onRetry={() => void todayQuery.refetch()} />
      </>
    )
  }

  return (
    <>
      <Breadcrumb
        items={[{ label: "Vue d'ensemble", to: '/tableau-de-bord' }, { label: 'Rapport du jour' }]}
      />
      <PageHeader
        title="Rapport de fin de journée"
        description={
          day
            ? `${formatDateLong(day)} — cochez ce que vous avez terminé, ajoutez ce qui n'a pas de numéro d'action. Tout s'enregistre au fur et à mesure.`
            : undefined
        }
        actions={
          <>
            {soumis ? (
              <Badge tone="green">
                <IconCheckCircle size={12} />
                Journée close
              </Badge>
            ) : ignoredCount > 0 ? (
              <Badge tone="orange">{ignoredCount} rappel{ignoredCount > 1 ? 's' : ''}</Badge>
            ) : null}
            <Button
              size="sm"
              variant="primary"
              loading={submitReport.isPending}
              onClick={clore}
              disabled={items.length === 0 && note.trim().length === 0}
            >
              <IconCheckCircle size={14} />
              {soumis ? 'Mettre à jour' : 'Clore la journée'}
            </Button>
          </>
        }
      />

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        {/* Rapport */}
        <div className="flex flex-col gap-6">
          <Card className="overflow-hidden">
            <CardHeader
              title="Ce que j'ai fait"
              description={
                items.length > 0
                  ? `${items.filter((item) => item.done).length} terminée(s) sur ${items.length}`
                  : 'Aucune ligne pour le moment.'
              }
            />
            <CardBody className="flex flex-col gap-2 p-4">
              {todayQuery.isLoading ? (
                Array.from({ length: 3 }, (_, index) => (
                  <Skeleton key={index} className="h-11 w-full rounded-[6px]" />
                ))
              ) : items.length === 0 ? (
                <p className="py-6 text-center text-[13px] text-fg-subtle">
                  Reprenez une suggestion à droite, ou saisissez une tâche ci-dessous.
                </p>
              ) : (
                items.map((item) => (
                  <div
                    key={item.key}
                    className="group flex items-center gap-3 rounded-[6px] border border-line bg-canvas px-3 py-2.5"
                  >
                    <button
                      type="button"
                      role="checkbox"
                      aria-checked={item.done}
                      onClick={() => basculer(item.key)}
                      aria-label={`Marquer « ${item.label} » comme terminée`}
                      className={cn(
                        'flex h-[18px] w-[18px] shrink-0 cursor-pointer items-center justify-center',
                        'rounded-[4px] border bg-canvas transition-colors',
                        // Monochrome : la coche prend la couleur du texte, pas
                        // une teinte de statut. Le contraste de la bordure
                        // suffit à distinguer coché de vide.
                        item.done
                          ? 'border-fg-subtle text-fg'
                          : 'border-line text-transparent hover:border-fg-subtle',
                      )}
                    >
                      <IconCheck size={13} />
                    </button>
                    {/* Une tâche faite reste pleinement lisible : la coche dit
                        déjà qu'elle est terminée, la barrer ne fait que gêner
                        la relecture du rapport. */}
                    <span className="min-w-0 flex-1 text-[13px] text-fg">{item.label}</span>
                    {item.actionId ? <Badge tone="blue">Action</Badge> : null}
                    <button
                      type="button"
                      onClick={() => retirer(item.key)}
                      aria-label="Retirer cette ligne"
                      className="shrink-0 cursor-pointer rounded-[4px] border-none bg-transparent p-1 text-fg-subtle opacity-0 transition-opacity hover:text-danger group-hover:opacity-100"
                    >
                      <IconTrash size={14} />
                    </button>
                  </div>
                ))
              )}

              <form onSubmit={ajouterManuelle} className="mt-2 flex items-end gap-2">
                <TextField
                  className="flex-1"
                  label="Ajouter une tâche"
                  placeholder="Ex : réunion de cadrage, dépannage poste comptabilité…"
                  value={nouveau}
                  onChange={(event) => setNouveau(event.target.value)}
                />
                <Button type="submit" size="sm" variant="secondary" disabled={!nouveau.trim()}>
                  <IconPlus size={14} />
                  Ajouter
                </Button>
              </form>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Note libre" description="Contexte, blocages, points à signaler." />
            <CardBody>
              <TextAreaField
                rows={3}
                placeholder="Optionnel"
                value={note}
                onChange={(event) => setNote(event.target.value)}
                onBlur={() => enregistrer(items, note)}
              />
            </CardBody>
          </Card>
        </div>

        {/* Suggestions */}
        <Card className="h-fit overflow-hidden">
          <CardHeader
            title="Vos actions du jour"
            description="Échéance aujourd'hui, modifiée aujourd'hui, ou restée en cours."
          />
          <CardBody className="flex flex-col gap-2 p-4">
            {todayQuery.isLoading ? (
              Array.from({ length: 3 }, (_, index) => (
                <Skeleton key={index} className="h-20 w-full rounded-[6px]" />
              ))
            ) : suggestions.length === 0 ? (
              <EmptyState
                className="border-0 bg-transparent px-2 py-6"
                icon={<IconClipboard size={36} strokeWidth={1.5} />}
                title="Rien à proposer"
                message="Aucune action ne vous est rattachée aujourd'hui. Saisissez vos tâches à la main."
              />
            ) : (
              suggestions.map((suggestion) => (
                <article
                  key={suggestion.action_id}
                  className="rounded-[6px] border border-line bg-canvas p-3"
                >
                  <div className="mb-1 flex flex-wrap items-center gap-1.5">
                    <span className="text-[12px] font-bold text-accent">{suggestion.numero}</span>
                    {suggestion.reasons.map((reason) => (
                      <Badge key={reason.code} tone={REASON_TONES[reason.code] ?? 'neutral'}>
                        {reason.label}
                      </Badge>
                    ))}
                  </div>
                  <p className="mb-2 line-clamp-2 text-[13px] text-fg">{suggestion.description}</p>
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" variant="primary" onClick={() => ajouterSuggestion(suggestion, true)}>
                      Terminée
                    </Button>
                    <Button size="sm" variant="secondary" onClick={() => ajouterSuggestion(suggestion, false)}>
                      En cours
                    </Button>
                  </div>
                </article>
              ))
            )}
          </CardBody>
        </Card>
      </div>
    </>
  )
}
