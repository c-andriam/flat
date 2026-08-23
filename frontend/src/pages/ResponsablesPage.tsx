import { useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'

import { type ApiError } from '@/api/client'
import { useCreateResponsable, useWorkloadReport } from '@/api/queries'
import type { ResponsableReport } from '@/api/types'
import { useAuth } from '@/auth/useAuth'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { formatDateShort, formatDateTime } from '@/lib/date'
import { formatPercent, hueFromString, initials } from '@/lib/format'
import { Badge } from '@/ui/Badge'
import { Breadcrumb } from '@/ui/Breadcrumb'
import { Button } from '@/ui/Button'
import { DataTable, type Column } from '@/ui/DataTable'
import { EmptyState } from '@/ui/EmptyState'
import { ErrorState } from '@/ui/ErrorState'
import { TextField } from '@/ui/Field'
import { IconPlus, IconUsers } from '@/ui/Icon'
import { Modal } from '@/ui/Modal'
import { PageHeader } from '@/ui/PageHeader'
import { ProgressBar } from '@/ui/ProgressBar'
import { StatCard, StatGrid } from '@/ui/StatCard'
import { useToast } from '@/ui/useToast'

export function ResponsablesPage() {
  const { canWrite } = useAuth()
  const [params, setParams] = useSearchParams()
  const [modalOpen, setModalOpen] = useState(false)

  const search = params.get('q') ?? ''
  const debouncedSearch = useDebouncedValue(search, 250)

  // Le rapport de charge porte à la fois l'identité et les compteurs :
  // une seule requête là où deux appels seraient à recroiser côté client.
  const workloadQuery = useWorkloadReport(true)
  const report = workloadQuery.data

  const needle = debouncedSearch.trim().toLowerCase()
  const rows = (report?.responsables ?? []).filter(
    (responsable) =>
      !needle ||
      responsable.display_name.toLowerCase().includes(needle) ||
      (responsable.email ?? '').toLowerCase().includes(needle),
  )

  const setSearch = (value: string) => {
    const next = new URLSearchParams(params)
    if (value) next.set('q', value)
    else next.delete('q')
    setParams(next, { replace: true })
  }

  const columns: Column<ResponsableReport>[] = [
    {
      key: 'name',
      header: 'Responsable',
      render: (responsable) => (
        <div className="flex items-center gap-2.5">
          <span
            aria-hidden="true"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[11px] font-bold"
            style={{
              backgroundColor: `hsl(${hueFromString(responsable.display_name)} 70% 50% / 0.15)`,
              color: `hsl(${hueFromString(responsable.display_name)} 70% 45%)`,
            }}
          >
            {initials(responsable.display_name)}
          </span>
          <div className="min-w-0">
            <p className="truncate font-medium text-fg">{responsable.display_name}</p>
            <p className="truncate text-[12px] text-fg-subtle">
              {responsable.email ?? 'Sans adresse email'}
            </p>
          </div>
        </div>
      ),
    },
    {
      key: 'mapped',
      header: 'Relances',
      render: (responsable) =>
        responsable.is_mapped ? (
          <Badge tone="green">Mappé</Badge>
        ) : (
          <Badge tone="orange">Non mappé</Badge>
        ),
      className: 'w-32',
      hideOnMobile: true,
    },
    {
      key: 'open',
      header: 'Ouvertes',
      render: (responsable) => <span className="tabular-nums">{responsable.open}</span>,
      className: 'w-24 text-center',
    },
    {
      key: 'overdue',
      header: 'Retards',
      render: (responsable) => (
        <span
          className={
            responsable.overdue > 0 ? 'font-semibold tabular-nums text-danger' : 'tabular-nums text-fg-muted'
          }
        >
          {responsable.overdue}
        </span>
      ),
      className: 'w-24 text-center',
    },
    {
      key: 'progress',
      header: 'Avancement',
      render: (responsable) => (
        <ProgressBar value={responsable.progress_avg} className="min-w-[110px]" />
      ),
      className: 'w-44',
      hideOnMobile: true,
    },
    {
      key: 'next',
      header: 'Prochaine échéance',
      render: (responsable) => (
        <span className="whitespace-nowrap text-fg-muted">
          {formatDateShort(responsable.next_deadline)}
        </span>
      ),
      className: 'w-40',
      hideOnMobile: true,
    },
    {
      key: 'relance',
      header: 'Dernière relance',
      render: (responsable) => (
        <span className="whitespace-nowrap text-fg-muted">
          {formatDateTime(responsable.last_relance_at)}
        </span>
      ),
      className: 'w-48',
      hideOnMobile: true,
    },
  ]

  const unmapped = (report?.responsables ?? []).filter((responsable) => !responsable.is_mapped).length

  return (
    <>
      <Breadcrumb
        items={[{ label: "Vue d'ensemble", to: '/tableau-de-bord' }, { label: 'Responsables' }]}
      />
      <PageHeader
        title="Responsables"
        description="Charge et ponctualité par personne, sur les projets actifs."
        actions={
          canWrite ? (
            <Button size="sm" variant="primary" onClick={() => setModalOpen(true)}>
              <IconPlus size={14} />
              Ajouter
            </Button>
          ) : null
        }
      />

      <StatGrid className="mb-6 lg:grid-cols-3">
        <StatCard
          compact
          label="Responsables"
          value={report?.responsable_count ?? 0}
          tone="blue"
          loading={workloadQuery.isLoading}
        />
        <StatCard
          compact
          label="Sans email"
          value={unmapped}
          tone="orange"
          loading={workloadQuery.isLoading}
          hint="Ces personnes ne reçoivent aucune relance."
        />
        <StatCard
          compact
          label="Actions non portées"
          value={report?.unassigned_actions ?? 0}
          tone="red"
          loading={workloadQuery.isLoading}
          hint="Invisibles de toute relance tant qu'aucun responsable n'y est rattaché."
        />
      </StatGrid>

      <div className="mb-4">
        <TextField
          className="max-w-sm"
          label="Rechercher"
          placeholder="Nom ou email…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>

      {workloadQuery.isError ? (
        <ErrorState error={workloadQuery.error} onRetry={() => void workloadQuery.refetch()} />
      ) : (
        <DataTable
          columns={columns}
          rows={rows}
          rowKey={(responsable) => responsable.responsable_id}
          loading={workloadQuery.isLoading}
          empty={
            <EmptyState
              icon={<IconUsers size={44} strokeWidth={1.5} />}
              title={needle ? 'Aucun responsable ne correspond' : 'Aucun responsable trouvé'}
              message={
                needle
                  ? 'Essayez un autre nom ou une autre adresse.'
                  : 'Ajoutez des responsables pour leur assigner des projets et des actions.'
              }
              action={
                canWrite && !needle ? (
                  <Button size="sm" variant="primary" onClick={() => setModalOpen(true)}>
                    <IconPlus size={14} />
                    Ajouter
                  </Button>
                ) : undefined
              }
            />
          }
        />
      )}

      {report ? (
        <p className="mt-3 text-[12px] text-fg-subtle">
          Charge calculée le {formatDateTime(report.generated_at)} · taux de retard moyen{' '}
          {formatPercent(
            rows.length > 0
              ? rows.reduce((sum, responsable) => sum + responsable.overdue_rate, 0) / rows.length
              : 0,
            1,
          )}
        </p>
      ) : null}

      <NewResponsableModal open={modalOpen} onClose={() => setModalOpen(false)} />
    </>
  )
}

function NewResponsableModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const toast = useToast()
  const createResponsable = useCreateResponsable()
  const [displayName, setDisplayName] = useState('')
  const [email, setEmail] = useState('')
  const [error, setError] = useState<string | null>(null)

  const close = () => {
    setDisplayName('')
    setEmail('')
    setError(null)
    onClose()
  }

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    if (!displayName.trim()) return setError('Le nom affiché est obligatoire.')

    createResponsable.mutate(
      { display_name: displayName.trim(), email: email.trim() || null },
      {
        onSuccess: (responsable) => {
          toast.success(`${responsable.display_name} ajouté(e).`)
          close()
        },
        onError: (apiError: ApiError) => setError(apiError.message),
      },
    )
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title="Nouveau responsable"
      footer={
        <>
          <Button size="sm" variant="secondary" onClick={close}>
            Annuler
          </Button>
          <Button
            size="sm"
            variant="primary"
            type="submit"
            form="new-responsable-form"
            loading={createResponsable.isPending}
          >
            Ajouter
          </Button>
        </>
      }
    >
      <form id="new-responsable-form" onSubmit={onSubmit} className="flex flex-col gap-4">
        <TextField
          label="Nom affiché"
          required
          placeholder="Ex : Andry Rakoto"
          hint="Doit correspondre au nom tel qu'il figure dans les classeurs Excel."
          value={displayName}
          onChange={(event) => setDisplayName(event.target.value)}
        />
        <TextField
          label="Adresse email"
          type="email"
          placeholder="prenom.nom@trimeta.mg"
          hint="Sans email, la personne ne reçoit aucune relance."
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
        {error ? (
          <p className="rounded-[6px] border border-danger/30 bg-danger-subtle px-3 py-2 text-[13px] font-medium text-danger">
            {error}
          </p>
        ) : null}
      </form>
    </Modal>
  )
}
