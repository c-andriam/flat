/**
 * Réglage et supervision des relances par email.
 *
 * Deux publics sur une même page. Tout le monde règle sa propre cadence — le
 * moteur envoyait auparavant la même chose à la même heure à tout le monde, et
 * un chef de projet qui suit quarante actions finissait par filtrer
 * l'expéditeur. Les administrateurs voient en plus la cadence de l'équipe,
 * l'aperçu de chaque message et l'historique des envois : sans cette vue, la
 * seule façon de vérifier qu'une relance était partie était de le demander à
 * son destinataire.
 */

import { useEffect, useMemo, useState } from 'react'

import { type ApiError } from '@/api/client'
import {
  useMyRelancePreference,
  useRelanceConfig,
  useRelanceDigest,
  useRelanceLogs,
  useRelancePreferences,
  useSendRelanceDigest,
  useSendRelanceDigestBatch,
  useUpdateMyRelancePreference,
  useUpdateRelancePreference,
} from '@/api/queries'
import {
  JOURS_SEMAINE,
  RELANCE_PERIMETRE_LABELS,
  type RelancePerimetre,
  type RelancePreference,
  type RelanceLog,
  type RelancePreferenceUpdate,
  type Uuid,
} from '@/api/types'
import { useAuth } from '@/auth/useAuth'
import { formatDateTime } from '@/lib/date'
import { cn } from '@/lib/cn'
import { hueFromString, initials } from '@/lib/format'
import { Badge } from '@/ui/Badge'
import { Breadcrumb } from '@/ui/Breadcrumb'
import { Button } from '@/ui/Button'
import { Card, CardBody, CardHeader } from '@/ui/Card'
import { DataTable, type Column } from '@/ui/DataTable'
import { EmptyState } from '@/ui/EmptyState'
import { ErrorState } from '@/ui/ErrorState'
import { SelectField } from '@/ui/Field'
import { IconAlert, IconCheckCircle, IconMail } from '@/ui/Icon'
import { Modal } from '@/ui/Modal'
import { PageHeader } from '@/ui/PageHeader'
import { Skeleton } from '@/ui/Skeleton'
import { StatCard, StatGrid } from '@/ui/StatCard'
import { useToast } from '@/ui/useToast'

/** Les quatre sections activables, telles que nommées par l'API. */
type SectionChamp =
  | 'include_overdue'
  | 'include_today'
  | 'include_due_soon'
  | 'include_pending'

/** Sections du récapitulatif, avec ce que chacune recouvre. */
const SECTIONS = [
  {
    champ: 'include_overdue',
    label: 'En retard',
    aide: 'Échéance dépassée, action non terminée.',
  },
  {
    champ: 'include_today',
    label: "À rendre aujourd'hui",
    aide: 'Échéance au jour même.',
  },
  {
    champ: 'include_due_soon',
    label: 'Échéances proches',
    aide: "Dans les jours qui suivent, selon l'horizon choisi.",
  },
  {
    champ: 'include_pending',
    label: 'En attente',
    aide: 'Ouvertes sans échéance, ou à échéance lointaine.',
  },
] as const satisfies readonly { champ: SectionChamp; label: string; aide: string }[]

const HEURES = Array.from({ length: 24 }, (_, h) => ({
  value: String(h),
  label: `${String(h).padStart(2, '0')} h`,
}))

const HORIZONS = [1, 2, 3, 5, 7, 14, 30].map((j) => ({
  value: String(j),
  label: j === 1 ? '1 jour' : `${j} jours`,
}))

const PERIMETRES = (
  Object.keys(RELANCE_PERIMETRE_LABELS) as RelancePerimetre[]
).map((value) => ({ value, label: RELANCE_PERIMETRE_LABELS[value] }))

export function RelancesPage() {
  const { hasRole } = useAuth()
  const isAdmin = hasRole('admin')

  return (
    <>
      <Breadcrumb
        items={[{ label: "Vue d'ensemble", to: '/tableau-de-bord' }, { label: 'Relances' }]}
      />
      <PageHeader
        title="Relances"
        description="Récapitulatif automatique des actions envoyé à leurs responsables de suivi."
      />

      <EtatEnvoi />
      <MesReglages />
      {isAdmin ? <ReglagesEquipe /> : null}
      {isAdmin ? <HistoriqueEnvois /> : null}
    </>
  )
}

/* ------------------------------------------------------------------ */
/* État de la configuration d'envoi                                    */
/* ------------------------------------------------------------------ */

function EtatEnvoi() {
  const { canWrite } = useAuth()
  // La route `/relances/config` est réservée aux comptes en écriture : un
  // lecteur n'a pas à savoir quelle boîte technique expédie les messages.
  const configQuery = useRelanceConfig(canWrite)

  if (!canWrite || configQuery.isLoading || configQuery.isError) return null
  const config = configQuery.data
  if (!config) return null

  const reel = config.mode === 'graph'
  return (
    <div
      className={cn(
        'mb-6 flex items-start gap-3 rounded-[8px] border px-4 py-3 text-[13px]',
        reel
          ? 'border-success/30 bg-success-subtle text-success'
          : 'border-warning/30 bg-warning-subtle text-warning',
      )}
      role="status"
    >
      {reel ? (
        <IconCheckCircle size={16} className="mt-0.5 shrink-0" />
      ) : (
        <IconAlert size={16} className="mt-0.5 shrink-0" />
      )}
      <div className="min-w-0">
        <p className="font-medium">
          {reel ? 'Les emails partent réellement.' : 'Mode simulation — aucun email ne part.'}
        </p>
        <p className="mt-0.5 opacity-90">{config.explanation}</p>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Mes réglages                                                        */
/* ------------------------------------------------------------------ */

function MesReglages() {
  const toast = useToast()
  const preferenceQuery = useMyRelancePreference()
  const update = useUpdateMyRelancePreference()

  const enregistrer = (patch: RelancePreferenceUpdate) =>
    update.mutate(patch, {
      onSuccess: () => toast.success('Réglages enregistrés.'),
      onError: (error: ApiError) => toast.error(error.message),
    })

  if (preferenceQuery.isLoading) {
    return (
      <Card className="mb-6">
        <CardHeader title="Mes relances" />
        <CardBody>
          <Skeleton className="h-32 w-full" />
        </CardBody>
      </Card>
    )
  }

  // Un compte sans fiche responsable rattachée ne figure dans aucune relance :
  // le dire explicitement vaut mieux qu'un formulaire sans effet.
  if (preferenceQuery.isError || !preferenceQuery.data) {
    return (
      <Card className="mb-6">
        <CardHeader title="Mes relances" />
        <CardBody>
          <EmptyState
            icon={<IconMail size={40} strokeWidth={1.5} />}
            title="Vous ne recevez aucune relance"
            message={
              preferenceQuery.error?.status === 404
                ? "Votre compte n'est rattaché à aucune fiche responsable. Demandez à un administrateur d'associer votre adresse à votre nom tel qu'il figure dans les classeurs."
                : (preferenceQuery.error?.message ?? 'Réglages indisponibles.')
            }
          />
        </CardBody>
      </Card>
    )
  }

  return (
    <FormulaireReglages
      titre="Mes relances"
      preference={preferenceQuery.data}
      enregistrer={enregistrer}
      enCours={update.isPending}
      className="mb-6"
    />
  )
}

/* ------------------------------------------------------------------ */
/* Formulaire de réglage, partagé entre « moi » et l'administration    */
/* ------------------------------------------------------------------ */

function FormulaireReglages({
  titre,
  preference,
  enregistrer,
  enCours,
  className,
}: {
  titre: string
  preference: RelancePreference
  enregistrer: (patch: RelancePreferenceUpdate) => void
  enCours: boolean
  className?: string
}) {
  // État local pour que les jours se cochent sans attendre l'aller-retour ;
  // resynchronisé dès que le serveur renvoie les réglages effectifs.
  const [jours, setJours] = useState<number[]>(preference.days_of_week)
  useEffect(() => setJours(preference.days_of_week), [preference.days_of_week])

  const sectionsActives = SECTIONS.filter((section) => preference[section.champ]).length

  const basculerJour = (jour: number) => {
    const suivant = jours.includes(jour)
      ? jours.filter((j) => j !== jour)
      : [...jours, jour].sort((a, b) => a - b)
    // Le serveur refuse une liste vide : couper les relances se fait par
    // l'interrupteur, ce qui préserve le réglage pour la reprise.
    if (suivant.length === 0) return
    setJours(suivant)
    enregistrer({ days_of_week: suivant })
  }

  const basculerSection = (champ: SectionChamp, valeur: boolean) => {
    // Décocher la dernière section produirait un message vide, que le serveur
    // refuse d'envoyer. On l'empêche ici pour que le refus soit lisible.
    if (!valeur && sectionsActives <= 1) return
    // Affectation indexée plutôt qu'un littéral à clé calculée : celui-ci
    // produirait une signature d'index, non assignable au type de patch.
    const patch: RelancePreferenceUpdate = {}
    patch[champ] = valeur
    enregistrer(patch)
  }

  return (
    <Card className={className}>
      <CardHeader
        title={titre}
        description={
          preference.enabled
            ? preference.cadence
            : 'Relances suspendues — aucun récapitulatif ne part.'
        }
        actions={
          <label className="flex cursor-pointer items-center gap-2 text-[13px] font-medium text-fg">
            <input
              type="checkbox"
              className="h-4 w-4 cursor-pointer accent-accent"
              checked={preference.enabled}
              disabled={enCours}
              onChange={(event) => enregistrer({ enabled: event.target.checked })}
            />
            Recevoir les relances
          </label>
        }
      />

      <CardBody className="flex flex-col gap-5">
        {!preference.is_mapped ? (
          <p className="rounded-[6px] border border-warning/30 bg-warning-subtle px-3 py-2 text-[13px] text-warning">
            Aucune adresse email n'est associée à cette fiche : le réglage est
            enregistré mais rien ne peut partir.
          </p>
        ) : null}

        <fieldset disabled={!preference.enabled || enCours} className="contents">
          <div>
            <p className="mb-2 text-[13px] font-medium text-fg">
              Jours d'envoi
              <span className="ml-2 font-normal text-fg-subtle">
                {jours.length} fois par semaine
              </span>
            </p>
            <div className="flex flex-wrap gap-1.5">
              {JOURS_SEMAINE.map((jour) => {
                const actif = jours.includes(jour.value)
                return (
                  <button
                    key={jour.value}
                    type="button"
                    aria-pressed={actif}
                    aria-label={jour.label}
                    title={jour.label}
                    disabled={!preference.enabled || enCours}
                    onClick={() => basculerJour(jour.value)}
                    className={cn(
                      'h-9 w-9 rounded-[6px] border text-[13px] font-semibold transition-colors',
                      'disabled:cursor-not-allowed disabled:opacity-50',
                      actif
                        ? 'border-accent bg-accent text-white'
                        : 'border-line bg-surface text-fg-muted hover:border-accent/40',
                    )}
                  >
                    {jour.court}
                  </button>
                )
              })}
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <SelectField
              label="Heure d'envoi"
              hint="Heure locale d'Antananarivo."
              value={String(preference.send_hour)}
              options={HEURES}
              onChange={(event) =>
                enregistrer({ send_hour: Number(event.target.value) })
              }
            />
            <SelectField
              label="Actions concernées"
              hint="Le suivi désigne la colonne « Resp. suivi » du classeur."
              value={preference.perimeter}
              options={PERIMETRES}
              onChange={(event) =>
                enregistrer({ perimeter: event.target.value as RelancePerimetre })
              }
            />
          </div>

          <div>
            <p className="mb-2 text-[13px] font-medium text-fg">Contenu du message</p>
            <div className="grid gap-2 sm:grid-cols-2">
              {SECTIONS.map((section) => {
                const coche = preference[section.champ]
                const derniere = coche && sectionsActives <= 1
                return (
                  <label
                    key={section.champ}
                    className={cn(
                      'flex items-start gap-2.5 rounded-[6px] border border-line px-3 py-2.5',
                      derniere ? 'cursor-not-allowed opacity-70' : 'cursor-pointer',
                    )}
                    title={
                      derniere
                        ? 'Au moins une section doit rester active : sans elle, le message serait vide.'
                        : undefined
                    }
                  >
                    <input
                      type="checkbox"
                      className="mt-0.5 h-4 w-4 accent-accent"
                      checked={coche}
                      disabled={derniere || !preference.enabled || enCours}
                      onChange={(event) =>
                        basculerSection(section.champ, event.target.checked)
                      }
                    />
                    <span className="min-w-0">
                      <span className="block text-[13px] font-medium text-fg">
                        {section.label}
                      </span>
                      <span className="block text-[12px] text-fg-subtle">{section.aide}</span>
                    </span>
                  </label>
                )
              })}
            </div>
          </div>

          {preference.include_due_soon ? (
            <SelectField
              className="max-w-xs"
              label="Horizon des échéances proches"
              hint="Au-delà, les actions basculent dans « en attente »."
              value={String(preference.horizon_days)}
              options={HORIZONS}
              onChange={(event) =>
                enregistrer({ horizon_days: Number(event.target.value) })
              }
            />
          ) : null}
        </fieldset>

        {!preference.personnalise ? (
          <p className="text-[12px] text-fg-subtle">
            Réglages par défaut — rien n'a encore été personnalisé ici.
          </p>
        ) : null}
      </CardBody>
    </Card>
  )
}

/* ------------------------------------------------------------------ */
/* Réglages de l'équipe (administrateurs)                              */
/* ------------------------------------------------------------------ */

function ReglagesEquipe() {
  const toast = useToast()
  const [tous, setTous] = useState(false)
  const [apercu, setApercu] = useState<RelancePreference | null>(null)

  const preferencesQuery = useRelancePreferences(tous)
  const update = useUpdateRelancePreference()
  const envoyerLot = useSendRelanceDigestBatch()

  const lignes = preferencesQuery.data ?? []
  const stats = useMemo(
    () => ({
      total: lignes.length,
      actifs: lignes.filter((p) => p.enabled && p.is_mapped).length,
      coupes: lignes.filter((p) => !p.enabled).length,
      sansEmail: lignes.filter((p) => !p.is_mapped).length,
    }),
    [lignes],
  )

  const campagne = (dryRun: boolean) =>
    envoyerLot.mutate(dryRun, {
      onSuccess: (lot) => {
        const detail = `${lot.sent} envoyé(s), ${lot.simulated} simulé(s), ${lot.failed} en échec`
        if (dryRun) toast.info(`Simulation : ${lot.considered} destinataire(s) — ${detail}.`)
        else toast.success(`Campagne terminée : ${detail}.`)
      },
      onError: (error: ApiError) => toast.error(error.message),
    })

  const colonnes: Column<RelancePreference>[] = [
    {
      key: 'personne',
      header: 'Responsable',
      render: (preference) => (
        <div className="flex items-center gap-2.5">
          <span
            aria-hidden="true"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[11px] font-bold"
            style={{
              backgroundColor: `hsl(${hueFromString(preference.responsable_name)} 70% 50% / 0.15)`,
              color: `hsl(${hueFromString(preference.responsable_name)} 70% 45%)`,
            }}
          >
            {initials(preference.responsable_name)}
          </span>
          <div className="min-w-0">
            <p className="truncate font-medium text-fg">{preference.responsable_name}</p>
            <p className="truncate text-[12px] text-fg-subtle">
              {preference.email ?? 'Sans adresse email'}
            </p>
          </div>
        </div>
      ),
    },
    {
      key: 'cadence',
      header: 'Cadence',
      render: (preference) =>
        preference.enabled ? (
          <span className="text-fg-muted">
            {preference.jours_labels.join(', ')} · {String(preference.send_hour).padStart(2, '0')} h
          </span>
        ) : (
          <Badge tone="neutral">Suspendues</Badge>
        ),
      className: 'w-64',
      hideOnMobile: true,
    },
    {
      key: 'perimetre',
      header: 'Périmètre',
      render: (preference) => (
        <span className="text-fg-muted">
          {RELANCE_PERIMETRE_LABELS[preference.perimeter]}
        </span>
      ),
      className: 'w-44',
      hideOnMobile: true,
    },
    {
      key: 'etat',
      header: 'État',
      render: (preference) =>
        !preference.is_mapped ? (
          <Badge tone="orange">Sans email</Badge>
        ) : preference.personnalise ? (
          <Badge tone="blue">Personnalisé</Badge>
        ) : (
          <Badge tone="neutral">Par défaut</Badge>
        ),
      className: 'w-36',
      hideOnMobile: true,
    },
    {
      key: 'actions',
      header: '',
      render: (preference) => (
        <div className="flex justify-end gap-1.5">
          <Button size="sm" variant="ghost" onClick={() => setApercu(preference)}>
            Aperçu
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={update.isPending}
            onClick={() =>
              update.mutate(
                {
                  responsableId: preference.responsable_id,
                  payload: { enabled: !preference.enabled },
                },
                {
                  onSuccess: () =>
                    toast.success(
                      preference.enabled
                        ? `Relances suspendues pour ${preference.responsable_name}.`
                        : `Relances réactivées pour ${preference.responsable_name}.`,
                    ),
                  onError: (error: ApiError) => toast.error(error.message),
                },
              )
            }
          >
            {preference.enabled ? 'Suspendre' : 'Réactiver'}
          </Button>
        </div>
      ),
      className: 'w-52',
    },
  ]

  return (
    <>
      <StatGrid className="mb-4 lg:grid-cols-4">
        <StatCard compact label="Destinataires" value={stats.total} tone="blue" />
        <StatCard compact label="Actifs" value={stats.actifs} tone="green" />
        <StatCard
          compact
          label="Suspendus"
          value={stats.coupes}
          tone="neutral"
          hint="Ont coupé leurs relances."
        />
        <StatCard
          compact
          label="Sans email"
          value={stats.sansEmail}
          tone="orange"
          hint="Ne reçoivent rien tant que l'adresse n'est pas renseignée."
        />
      </StatGrid>

      <Card className="mb-6">
        <CardHeader
          title="Cadence de l'équipe"
          description="Chaque personne peut modifier ses propres réglages ; vous pouvez les ajuster ici."
          actions={
            <div className="flex flex-wrap items-center gap-2">
              <label className="flex cursor-pointer items-center gap-2 text-[13px] text-fg-muted">
                <input
                  type="checkbox"
                  className="h-4 w-4 cursor-pointer accent-accent"
                  checked={tous}
                  onChange={(event) => setTous(event.target.checked)}
                />
                Inclure les non mappés
              </label>
              <Button
                size="sm"
                variant="secondary"
                loading={envoyerLot.isPending}
                onClick={() => campagne(true)}
              >
                Simuler
              </Button>
              <Button
                size="sm"
                variant="primary"
                loading={envoyerLot.isPending}
                onClick={() => campagne(false)}
              >
                <IconMail size={14} />
                Envoyer maintenant
              </Button>
            </div>
          }
        />
        <CardBody className="p-0">
          {preferencesQuery.isError ? (
            <div className="p-5">
              <ErrorState
                error={preferencesQuery.error}
                onRetry={() => void preferencesQuery.refetch()}
              />
            </div>
          ) : (
            <DataTable
              columns={colonnes}
              rows={lignes}
              rowKey={(preference) => preference.responsable_id}
              loading={preferencesQuery.isLoading}
              empty={
                <EmptyState
                  icon={<IconMail size={44} strokeWidth={1.5} />}
                  title="Aucun destinataire"
                  message="Associez une adresse email aux responsables pour qu'ils reçoivent les relances."
                />
              }
            />
          )}
        </CardBody>
      </Card>

      <ApercuDigest
        responsable={apercu}
        onClose={() => setApercu(null)}
      />
    </>
  )
}

/* ------------------------------------------------------------------ */
/* Aperçu du récapitulatif d'une personne                              */
/* ------------------------------------------------------------------ */

function ApercuDigest({
  responsable,
  onClose,
}: {
  responsable: RelancePreference | null
  onClose: () => void
}) {
  const toast = useToast()
  const digestQuery = useRelanceDigest(responsable?.responsable_id ?? null)
  const envoyer = useSendRelanceDigest()
  const digest = digestQuery.data

  const envoi = (id: Uuid) =>
    envoyer.mutate(id, {
      onSuccess: (resultat) => {
        if (resultat.status === 'sent')
          toast.success(`Récapitulatif envoyé à ${resultat.email}.`)
        else if (resultat.status === 'simulated')
          toast.info('Envoi simulé : la configuration Azure est incomplète.')
        else toast.error(resultat.detail ?? "L'envoi n'a pas abouti.")
        onClose()
      },
      onError: (error: ApiError) => toast.error(error.message),
    })

  return (
    <Modal
      open={responsable !== null}
      onClose={onClose}
      size="lg"
      title={
        responsable ? `Récapitulatif de ${responsable.responsable_name}` : 'Récapitulatif'
      }
      footer={
        <>
          <Button size="sm" variant="secondary" onClick={onClose}>
            Fermer
          </Button>
          <Button
            size="sm"
            variant="primary"
            loading={envoyer.isPending}
            disabled={!digest?.would_send}
            onClick={() => responsable && envoi(responsable.responsable_id)}
          >
            <IconMail size={14} />
            Envoyer maintenant
          </Button>
        </>
      }
    >
      {digestQuery.isLoading ? (
        <Skeleton className="h-48 w-full" />
      ) : digestQuery.isError ? (
        <ErrorState error={digestQuery.error} onRetry={() => void digestQuery.refetch()} />
      ) : digest ? (
        <div className="flex flex-col gap-4">
          <div className="rounded-[6px] border border-line bg-inset px-3 py-2.5">
            <p className="text-[13px] font-semibold text-fg">{digest.subject}</p>
            <p className="mt-0.5 text-[12px] text-fg-subtle">
              À {digest.email ?? 'aucune adresse'} ·{' '}
              {digest.next_send_at
                ? `prochain envoi automatique le ${formatDateTime(digest.next_send_at)}`
                : 'aucun envoi automatique programmé'}
            </p>
          </div>

          {digest.skip_reason ? (
            <p className="rounded-[6px] border border-warning/30 bg-warning-subtle px-3 py-2 text-[13px] text-warning">
              {digest.skip_reason}
            </p>
          ) : null}

          {digest.sections
            .filter((section) => section.action_count > 0)
            .map((section) => (
              <div key={section.key}>
                <p className="mb-1.5 text-[13px] font-semibold text-fg">
                  {section.label}
                  <span className="ml-2 font-normal text-fg-subtle">
                    {section.action_count}
                  </span>
                </p>
                <ul className="flex flex-col gap-1">
                  {section.actions.map((action) => (
                    <li
                      key={action.id}
                      className="flex items-baseline gap-2 rounded-[4px] border border-line px-2.5 py-1.5 text-[13px]"
                    >
                      <span className="shrink-0 font-mono text-[11px] text-fg-subtle">
                        {action.project_code} {action.numero}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-fg">
                        {action.description}
                      </span>
                      <span className="shrink-0 tabular-nums text-fg-subtle">
                        {Math.round(action.progress)} %
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}

          {digest.action_count === 0 ? (
            <EmptyState
              icon={<IconCheckCircle size={40} strokeWidth={1.5} />}
              title="Rien à signaler"
              message="Aucune action ne correspond au périmètre de cette personne."
            />
          ) : null}
        </div>
      ) : null}
    </Modal>
  )
}

/* ------------------------------------------------------------------ */
/* Historique des envois                                               */
/* ------------------------------------------------------------------ */

function HistoriqueEnvois() {
  const logsQuery = useRelanceLogs(25)
  const lignes = logsQuery.data?.items ?? []

  const colonnes: Column<RelanceLog>[] = [
    {
      key: 'date',
      header: 'Envoyé le',
      render: (log) => (
        <span className="whitespace-nowrap text-fg-muted">{formatDateTime(log.sent_at)}</span>
      ),
      className: 'w-52',
    },
    {
      key: 'nature',
      header: 'Nature',
      render: (log) => (
        <Badge tone={log.kind === 'digest' ? 'blue' : 'neutral'}>
          {log.kind === 'digest' ? 'Récapitulatif' : log.kind}
        </Badge>
      ),
      className: 'w-40',
      hideOnMobile: true,
    },
    {
      key: 'actions',
      header: 'Actions citées',
      render: (log) => <span className="tabular-nums">{log.action_count}</span>,
      className: 'w-36 text-center',
    },
    {
      key: 'statut',
      header: 'Statut',
      render: (log) => (
        <Badge tone={log.email_status === 'sent' ? 'green' : 'orange'}>
          {log.email_status === 'sent' ? 'Envoyé' : 'Simulé'}
        </Badge>
      ),
      className: 'w-32',
    },
  ]

  return (
    <Card>
      <CardHeader
        title="Derniers envois"
        description="Trace d'audit : sans elle, vérifier qu'une relance est bien partie demandait de le demander à son destinataire."
      />
      <CardBody className="p-0">
        <DataTable
          columns={colonnes}
          rows={lignes}
          rowKey={(log) => log.id}
          loading={logsQuery.isLoading}
          empty={
            <EmptyState
              icon={<IconMail size={44} strokeWidth={1.5} />}
              title="Aucun envoi enregistré"
              message="Les récapitulatifs partent aux jours et heures réglés par chacun."
            />
          }
        />
      </CardBody>
    </Card>
  )
}
