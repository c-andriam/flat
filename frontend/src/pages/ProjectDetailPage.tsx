import { useState } from 'react'
import { useParams } from 'react-router-dom'

import { useProject, useProjectReport } from '@/api/queries'
import type { Action } from '@/api/types'
import { useAuth } from '@/auth/useAuth'
import { ActionStatusBadge } from '@/features/actions/ActionStatusBadge'
import { DeadlineCell } from '@/features/actions/DeadlineCell'
import { NewActionModal } from '@/features/actions/NewActionModal'
import { formatDateTime } from '@/lib/date'
import { formatHj, formatPercent } from '@/lib/format'
import { Badge } from '@/ui/Badge'
import { Breadcrumb } from '@/ui/Breadcrumb'
import { Button } from '@/ui/Button'
import { Card, CardHeader } from '@/ui/Card'
import { DataTable, type Column } from '@/ui/DataTable'
import { EmptyState } from '@/ui/EmptyState'
import { ErrorState } from '@/ui/ErrorState'
import { IconActivity, IconPlus } from '@/ui/Icon'
import { PageHeader } from '@/ui/PageHeader'
import { ProgressBar } from '@/ui/ProgressBar'
import { StatCard, StatGrid } from '@/ui/StatCard'

export function ProjectDetailPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const { canWrite } = useAuth()
  const [modalOpen, setModalOpen] = useState(false)

  const projectQuery = useProject(projectId)
  const reportQuery = useProjectReport(projectId)

  const project = projectQuery.data
  const report = reportQuery.data

  const columns: Column<Action>[] = [
    {
      key: 'numero',
      header: 'N°',
      render: (action) => <span className="font-semibold text-fg">{action.numero}</span>,
      className: 'w-32',
    },
    {
      key: 'description',
      header: 'Description',
      render: (action) => <span className="line-clamp-2">{action.description}</span>,
    },
    {
      key: 'responsables',
      header: 'Responsables',
      render: (action) => (
        <span className="text-fg-muted">
          {action.responsables.length > 0
            ? action.responsables.map((responsable) => responsable.display_name).join(', ')
            : '—'}
        </span>
      ),
      className: 'w-48',
      hideOnMobile: true,
    },
    {
      key: 'progress',
      header: 'Avancement',
      render: (action) => <ProgressBar value={action.progress} className="min-w-[110px]" />,
      className: 'w-44',
      hideOnMobile: true,
    },
    {
      key: 'deadline',
      header: 'Échéance',
      render: (action) => <DeadlineCell deadline={action.deadline} status={action.status} />,
      className: 'w-28',
    },
    {
      key: 'status',
      header: 'Statut',
      render: (action) => <ActionStatusBadge status={action.status} />,
      className: 'w-32',
    },
  ]

  if (projectQuery.isError) {
    return (
      <>
        <Breadcrumb
          items={[
            { label: "Vue d'ensemble", to: '/tableau-de-bord' },
            { label: 'Projets', to: '/projets' },
            { label: 'Fiche projet' },
          ]}
        />
        <ErrorState
          error={projectQuery.error}
          onRetry={() => void projectQuery.refetch()}
          title={projectQuery.error.isNotFound ? 'Projet introuvable' : 'Chargement impossible'}
        />
      </>
    )
  }

  return (
    <>
      <Breadcrumb
        items={[
          { label: "Vue d'ensemble", to: '/tableau-de-bord' },
          { label: 'Projets', to: '/projets' },
          { label: project?.code ?? 'Fiche projet' },
        ]}
      />

      <PageHeader
        title={project ? `${project.code} — ${project.name}` : 'Chargement…'}
        description={
          project ? (
            <span className="flex flex-wrap items-center gap-2">
              {project.is_active ? <Badge tone="green">Actif</Badge> : <Badge tone="neutral">Archivé</Badge>}
              {project.has_phases ? <Badge tone="purple">Par phases</Badge> : null}
              <span>Dernière synchro : {formatDateTime(project.last_synced_at)}</span>
            </span>
          ) : undefined
        }
        actions={
          canWrite ? (
            <Button size="sm" variant="primary" onClick={() => setModalOpen(true)}>
              <IconPlus size={14} />
              Nouvelle action
            </Button>
          ) : null
        }
      />

      <StatGrid>
        <StatCard
          compact
          label="Actions"
          value={report?.total_actions ?? 0}
          tone="blue"
          loading={reportQuery.isLoading}
          hint={report ? `${report.done} terminées · ${report.open} ouvertes` : undefined}
        />
        <StatCard
          compact
          label="Avancement moyen"
          value={formatPercent(report?.progress_avg)}
          tone="green"
          loading={reportQuery.isLoading}
          hint={report ? `Achèvement : ${formatPercent(report.completion_rate)}` : undefined}
        />
        <StatCard
          compact
          label="En retard"
          value={report?.overdue ?? 0}
          tone="orange"
          loading={reportQuery.isLoading}
          hint={report ? `${formatPercent(report.overdue_rate, 1)} des ouvertes` : undefined}
        />
        <StatCard
          compact
          label="Charges estimées"
          value={formatHj(report?.charges_hj_total)}
          tone="purple"
          loading={reportQuery.isLoading}
          hint={report ? `SPI ${formatPercent(report.spi_avg)} · OTD ${formatPercent(report.otd_avg)}` : undefined}
        />
      </StatGrid>

      <div className="mt-8">
        <Card className="overflow-hidden">
          <CardHeader
            title="Actions du projet"
            description={
              project ? `${project.actions.length} action(s) rattachée(s) à ce projet.` : undefined
            }
          />
          <DataTable
            columns={columns}
            rows={project?.actions ?? []}
            rowKey={(action) => action.id}
            loading={projectQuery.isLoading}
            className="rounded-none border-0"
            empty={
              <EmptyState
                className="rounded-none border-0 border-t border-line"
                icon={<IconActivity size={44} strokeWidth={1.5} />}
                title="Aucune action"
                message="Ce projet n'a pas encore d'action enregistrée."
                action={
                  canWrite ? (
                    <Button size="sm" variant="primary" onClick={() => setModalOpen(true)}>
                      <IconPlus size={14} />
                      Nouvelle action
                    </Button>
                  ) : undefined
                }
              />
            }
          />
        </Card>
      </div>

      <NewActionModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        {...(projectId ? { defaultProjectId: projectId } : {})}
      />
    </>
  )
}
