import { Link } from 'react-router-dom'

import { useActionSummary, usePortfolioReport, useActions } from '@/api/queries'
import type { ProjectHealth } from '@/api/types'
import { ActionStatusBadge } from '@/features/actions/ActionStatusBadge'
import { DeadlineCell } from '@/features/actions/DeadlineCell'
import { formatDateTime } from '@/lib/date'
import { formatPercent } from '@/lib/format'
import { Badge, type BadgeTone } from '@/ui/Badge'
import { Breadcrumb } from '@/ui/Breadcrumb'
import { Card, CardHeader } from '@/ui/Card'
import { DataTable, type Column } from '@/ui/DataTable'
import { EmptyState } from '@/ui/EmptyState'
import { ErrorState } from '@/ui/ErrorState'
import { IconActivity, IconAlert, IconClock, IconFolder } from '@/ui/Icon'
import { PageHeader } from '@/ui/PageHeader'
import { ProgressBar } from '@/ui/ProgressBar'
import { StatCard, StatGrid } from '@/ui/StatCard'
import type { Action, ProjectReport } from '@/api/types'

const HEALTH_TONES: Record<ProjectHealth, BadgeTone> = {
  ok: 'green',
  attention: 'orange',
  critique: 'red',
}

const HEALTH_LABELS: Record<ProjectHealth, string> = {
  ok: 'Sain',
  attention: 'À surveiller',
  critique: 'Critique',
}

export function DashboardPage() {
  const summaryQuery = useActionSummary()
  const portfolioQuery = usePortfolioReport('active')
  // Les actions les plus urgentes d'abord : le tri par défaut de l'API place
  // les échéances les plus proches en tête.
  const urgentQuery = useActions({ view: 'overdue', limit: 6, active_projects_only: true })

  const counts = summaryQuery.data?.counts
  const projects = portfolioQuery.data?.projects ?? []
  const topProjects = [...projects]
    .sort((a, b) => b.overdue - a.overdue || b.open - a.open)
    .slice(0, 6)

  const projectColumns: Column<ProjectReport>[] = [
    {
      key: 'code',
      header: 'Projet',
      render: (project) => (
        <Link
          to={`/projets/${project.project_id}`}
          className="font-semibold text-accent no-underline hover:underline"
        >
          {project.code}
        </Link>
      ),
      className: 'w-24',
    },
    {
      key: 'name',
      header: 'Intitulé',
      render: (project) => <span className="line-clamp-1">{project.name}</span>,
    },
    {
      key: 'progress',
      header: 'Avancement',
      render: (project) => <ProgressBar value={project.progress_avg} className="min-w-[110px]" />,
      className: 'w-44',
      hideOnMobile: true,
    },
    {
      key: 'overdue',
      header: 'Retards',
      render: (project) => (
        <span className={project.overdue > 0 ? 'font-semibold text-danger' : 'text-fg-muted'}>
          {project.overdue}
        </span>
      ),
      className: 'w-20 text-center',
    },
    {
      key: 'health',
      header: 'Santé',
      render: (project) => (
        <Badge tone={HEALTH_TONES[project.health]}>{HEALTH_LABELS[project.health]}</Badge>
      ),
      className: 'w-32',
      hideOnMobile: true,
    },
  ]

  const actionColumns: Column<Action>[] = [
    {
      key: 'numero',
      header: 'N°',
      render: (action) => <span className="font-semibold text-fg">{action.numero}</span>,
      className: 'w-28',
    },
    {
      key: 'description',
      header: 'Description',
      render: (action) => <span className="line-clamp-1">{action.description}</span>,
    },
    {
      key: 'resp',
      header: 'Suivi',
      render: (action) => <span className="text-fg-muted">{action.resp_suivi ?? '—'}</span>,
      className: 'w-36',
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
      hideOnMobile: true,
    },
  ]

  if (summaryQuery.isError && portfolioQuery.isError) {
    return (
      <>
        <Breadcrumb items={[{ label: "Vue d'ensemble" }]} />
        <ErrorState error={summaryQuery.error} onRetry={() => void summaryQuery.refetch()} />
      </>
    )
  }

  return (
    <>
      <Breadcrumb items={[{ label: "Vue d'ensemble" }]} />
      <PageHeader
        title="Vue d'ensemble"
        description={
          summaryQuery.data
            ? `Compteurs calculés le ${formatDateTime(summaryQuery.data.generated_at)}.`
            : undefined
        }
      />

      <StatGrid>
        <StatCard
          compact
          label="Projets actifs"
          value={portfolioQuery.data?.project_count ?? 0}
          tone="blue"
          loading={portfolioQuery.isLoading}
          icon={<IconFolder size={18} />}
        />
        <StatCard
          compact
          label="Actions ouvertes"
          value={counts?.open ?? 0}
          tone="green"
          loading={summaryQuery.isLoading}
          icon={<IconActivity size={18} />}
        />
        <StatCard
          compact
          label="Actions en retard"
          value={counts?.overdue ?? 0}
          tone="orange"
          loading={summaryQuery.isLoading}
          icon={<IconAlert size={18} />}
          hint={
            summaryQuery.data
              ? `${formatPercent(summaryQuery.data.overdue_ratio, 1)} des actions ouvertes`
              : undefined
          }
        />
        <StatCard
          compact
          label="Échéances proches"
          value={counts?.due_soon ?? 0}
          tone="red"
          loading={summaryQuery.isLoading}
          icon={<IconClock size={18} />}
        />
      </StatGrid>

      <div className="mt-8">
        <Card className="overflow-hidden">
          <CardHeader
            title="Projets les plus exposés"
            description="Classés par nombre d'actions en retard, puis par actions ouvertes."
            actions={
              <Link
                to="/projets"
                className="text-[13px] font-medium text-accent no-underline hover:underline"
              >
                Tous les projets
              </Link>
            }
          />
          <DataTable
            columns={projectColumns}
            rows={topProjects}
            rowKey={(project) => project.project_id}
            loading={portfolioQuery.isLoading}
            className="rounded-none border-0"
            empty={
              <EmptyState
                className="rounded-none border-0 border-t border-line"
                icon={<IconFolder size={44} strokeWidth={1.5} />}
                title="Aucun projet actif"
                message="Les projets synchronisés depuis SharePoint apparaîtront ici."
              />
            }
          />
        </Card>
      </div>

      <div className="mt-8">
        <Card className="overflow-hidden">
          <CardHeader
            title="Actions prioritaires"
            description="Actions dont l'échéance est dépassée et qui restent ouvertes."
            actions={
              <Link
                to="/actions?vue=overdue"
                className="text-[13px] font-medium text-accent no-underline hover:underline"
              >
                Voir tout
              </Link>
            }
          />
          <DataTable
            columns={actionColumns}
            rows={urgentQuery.data?.items ?? []}
            rowKey={(action) => action.id}
            loading={urgentQuery.isLoading}
            className="rounded-none border-0"
            empty={
              <EmptyState
                className="rounded-none border-0 border-t border-line"
                icon={<IconActivity size={44} strokeWidth={1.5} />}
                title="Aucune action en retard"
                message="Toutes les échéances sont tenues — rien ne demande d'arbitrage."
              />
            }
          />
        </Card>
      </div>
    </>
  )
}
