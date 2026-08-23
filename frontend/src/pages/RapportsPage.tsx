import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { useForecastReport, usePortfolioReport, useRelanceConfig, useSyncLogs } from '@/api/queries'
import type { ProjectHealth, ProjectReport, SyncLog } from '@/api/types'
import { formatDateShort, formatDateTime } from '@/lib/date'
import { formatHj, formatNumber, formatPercent } from '@/lib/format'
import { cn } from '@/lib/cn'
import { Badge, type BadgeTone } from '@/ui/Badge'
import { Breadcrumb } from '@/ui/Breadcrumb'
import { Button } from '@/ui/Button'
import { Card, CardBody, CardHeader } from '@/ui/Card'
import { DataTable, type Column } from '@/ui/DataTable'
import { EmptyState } from '@/ui/EmptyState'
import { ErrorState } from '@/ui/ErrorState'
import { SelectField } from '@/ui/Field'
import { IconDownload, IconMail, IconPieChart, IconRefresh } from '@/ui/Icon'
import { PageHeader } from '@/ui/PageHeader'
import { ProgressBar } from '@/ui/ProgressBar'
import { StatCard, StatGrid } from '@/ui/StatCard'
import { useToast } from '@/ui/useToast'

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

const SYNC_TONES = {
  running: 'blue',
  success: 'green',
  failed: 'red',
} as const

/** Échappe une valeur pour le CSV : les intitulés contiennent des virgules. */
function csvCell(value: string | number | null | undefined): string {
  const text = value === null || value === undefined ? '' : String(value)
  return /[",;\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

function downloadCsv(filename: string, rows: (string | number | null)[][]): void {
  // Le BOM force Excel à lire l'UTF-8 : sans lui, « Échéance » arrive en « Ã‰chÃ©ance ».
  const csv = '﻿' + rows.map((row) => row.map(csvCell).join(';')).join('\r\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

export function RapportsPage() {
  const toast = useToast()
  const [scope, setScope] = useState<'active' | 'all'>('active')
  const [weeks, setWeeks] = useState(4)

  const portfolioQuery = usePortfolioReport(scope)
  const forecastQuery = useForecastReport({ weeks, include_actions: false })
  const relanceConfigQuery = useRelanceConfig()
  const syncLogsQuery = useSyncLogs(8)

  const report = portfolioQuery.data
  const totals = report?.totals.counts
  const projects = useMemo(
    () => [...(report?.projects ?? [])].sort((a, b) => b.overdue - a.overdue || a.code.localeCompare(b.code)),
    [report],
  )

  const exportPortfolio = () => {
    if (projects.length === 0) {
      toast.warning('Aucune donnée à exporter.')
      return
    }
    downloadCsv(`portefeuille-${scope}-${new Date().toISOString().slice(0, 10)}.csv`, [
      [
        'Code',
        'Projet',
        'Actif',
        'Actions',
        'Terminées',
        'Ouvertes',
        'En retard',
        'Bloquées',
        'Échéance proche',
        'Non assignées',
        'Avancement %',
        'Achèvement %',
        'Retard %',
        'SPI',
        'OTD',
        'Charges h/j',
        'Santé',
      ],
      ...projects.map((project) => [
        project.code,
        project.name,
        project.is_active ? 'oui' : 'non',
        project.total_actions,
        project.done,
        project.open,
        project.overdue,
        project.blocked,
        project.due_soon,
        project.unassigned,
        project.progress_avg.toFixed(1),
        project.completion_rate.toFixed(1),
        project.overdue_rate.toFixed(1),
        project.spi_avg.toFixed(1),
        project.otd_avg.toFixed(1),
        project.charges_hj_total.toFixed(1),
        HEALTH_LABELS[project.health],
      ]),
    ])
    toast.success(`${projects.length} projet(s) exporté(s).`)
  }

  const projectColumns: Column<ProjectReport>[] = [
    {
      key: 'code',
      header: 'Code',
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
      header: 'Projet',
      render: (project) => <span className="line-clamp-1">{project.name}</span>,
    },
    {
      key: 'actions',
      header: 'Actions',
      render: (project) => (
        <span className="tabular-nums text-fg-muted">
          {project.done}/{project.total_actions}
        </span>
      ),
      className: 'w-24 text-center',
      hideOnMobile: true,
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
        <span className={cn('tabular-nums', project.overdue > 0 ? 'font-semibold text-danger' : 'text-fg-muted')}>
          {project.overdue}
        </span>
      ),
      className: 'w-20 text-center',
    },
    {
      key: 'charges',
      header: 'Charges',
      render: (project) => (
        <span className="whitespace-nowrap text-fg-muted">{formatHj(project.charges_hj_total)}</span>
      ),
      className: 'w-28',
      hideOnMobile: true,
    },
    {
      key: 'health',
      header: 'Santé',
      render: (project) => (
        <Badge tone={HEALTH_TONES[project.health]}>{HEALTH_LABELS[project.health]}</Badge>
      ),
      className: 'w-32',
    },
  ]

  const syncColumns: Column<SyncLog>[] = [
    {
      key: 'started',
      header: 'Démarrée',
      render: (log) => <span className="whitespace-nowrap">{formatDateTime(log.started_at)}</span>,
      className: 'w-48',
    },
    {
      key: 'status',
      header: 'Résultat',
      render: (log) => <Badge tone={SYNC_TONES[log.status]}>{log.status}</Badge>,
      className: 'w-32',
    },
    {
      key: 'files',
      header: 'Fichiers',
      render: (log) => <span className="tabular-nums">{log.files_processed}</span>,
      className: 'w-24 text-center',
      hideOnMobile: true,
    },
    {
      key: 'error',
      header: 'Détail',
      render: (log) => (
        <span className="line-clamp-1 text-fg-muted">{log.error_message ?? '—'}</span>
      ),
    },
  ]

  const maxWeekCount = Math.max(1, ...(forecastQuery.data?.weeks ?? []).map((week) => week.action_count))

  return (
    <>
      <Breadcrumb items={[{ label: "Vue d'ensemble", to: '/tableau-de-bord' }, { label: 'Rapports' }]} />
      <PageHeader
        title="Rapports"
        description="Indicateurs consolidés du portefeuille, plan de charge et journal de synchronisation."
        actions={
          <>
            <Button size="sm" variant="secondary" onClick={() => void portfolioQuery.refetch()}>
              <IconRefresh size={14} />
              Actualiser
            </Button>
            <Button size="sm" variant="primary" onClick={exportPortfolio}>
              <IconDownload size={14} />
              Exporter en CSV
            </Button>
          </>
        }
      />

      <div className="mb-5 flex flex-wrap items-end gap-3">
        <SelectField
          className="w-52"
          label="Périmètre"
          value={scope}
          onChange={(event) => setScope(event.target.value as 'active' | 'all')}
          options={[
            { value: 'active', label: 'Projets actifs' },
            { value: 'all', label: 'Tous les projets' },
          ]}
        />
        <SelectField
          className="w-52"
          label="Horizon du plan de charge"
          value={String(weeks)}
          onChange={(event) => setWeeks(Number(event.target.value))}
          options={[
            { value: '4', label: '4 semaines' },
            { value: '8', label: '8 semaines' },
            { value: '12', label: '12 semaines' },
          ]}
        />
      </div>

      {portfolioQuery.isError ? (
        <ErrorState error={portfolioQuery.error} onRetry={() => void portfolioQuery.refetch()} />
      ) : (
        <>
          <StatGrid>
            <StatCard
              compact
              label="Projets"
              value={formatNumber(report?.project_count)}
              tone="blue"
              loading={portfolioQuery.isLoading}
            />
            <StatCard
              compact
              label="Actions ouvertes"
              value={formatNumber(totals?.open)}
              tone="green"
              loading={portfolioQuery.isLoading}
              hint={`${formatNumber(totals?.done)} terminées`}
            />
            <StatCard
              compact
              label="Taux de retard"
              value={formatPercent(report?.totals.overdue_ratio, 1)}
              tone="orange"
              loading={portfolioQuery.isLoading}
              hint="Un portefeuille sain reste sous 10 %."
            />
            <StatCard
              compact
              label="Actions non portées"
              value={formatNumber(totals?.unassigned)}
              tone="red"
              loading={portfolioQuery.isLoading}
            />
          </StatGrid>

          <div className="mt-8">
            <Card className="overflow-hidden">
              <CardHeader
                title="Portefeuille projet"
                description={
                  report ? `Généré le ${formatDateTime(report.generated_at)}.` : undefined
                }
              />
              <DataTable
                columns={projectColumns}
                rows={projects}
                rowKey={(project) => project.project_id}
                loading={portfolioQuery.isLoading}
                className="rounded-none border-0"
                empty={
                  <EmptyState
                    className="rounded-none border-0 border-t border-line"
                    icon={<IconPieChart size={44} strokeWidth={1.5} />}
                    title="Aucun rapport disponible"
                    message="Aucune donnée suffisante n'est disponible pour générer un rapport."
                  />
                }
              />
            </Card>
          </div>
        </>
      )}

      {/* Plan de charge */}
      <div className="mt-8">
        <Card>
          <CardHeader
            title="Plan de charge"
            description={
              forecastQuery.data
                ? `${forecastQuery.data.overdue_backlog} action(s) déjà en retard pèsent sur ces semaines sans y figurer.`
                : undefined
            }
          />
          <CardBody>
            {forecastQuery.isError ? (
              <ErrorState error={forecastQuery.error} onRetry={() => void forecastQuery.refetch()} />
            ) : forecastQuery.isLoading ? (
              <div className="flex h-40 items-end gap-3">
                {Array.from({ length: weeks }, (_, index) => (
                  <div key={index} className="animate-skeleton flex-1 rounded-t-[4px] bg-line" style={{ height: `${30 + index * 8}%` }} />
                ))}
              </div>
            ) : (
              <div className="flex h-56 gap-3">
                {(forecastQuery.data?.weeks ?? []).map((week) => (
                  <div
                    key={week.week_start}
                    className="flex h-full min-w-0 flex-1 flex-col items-center gap-2"
                  >
                    <span className="text-[12px] font-semibold tabular-nums text-fg">
                      {week.action_count}
                    </span>

                    {/* Piste de hauteur définie : une barre en `height: X%` sur un
                        parent en hauteur automatique se résout à zéro, et seuls le
                        chiffre et la date restaient visibles. */}
                    <div className="relative w-full min-h-0 flex-1">
                      <div
                        className="absolute inset-x-0 bottom-0 rounded-t-[4px] bg-accent transition-[height] duration-500"
                        style={{
                          height: `${Math.max(2, (week.action_count / maxWeekCount) * 100)}%`,
                        }}
                        title={`${week.label} · ${week.action_count} action(s) · ${formatHj(week.charges_hj)}`}
                      />
                    </div>

                    <span className="w-full truncate text-center text-[11px] text-fg-subtle">
                      {formatDateShort(week.week_start)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </CardBody>
        </Card>
      </div>

      {/* Relances + synchronisations */}
      <div className="mt-8 grid grid-cols-1 gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader title="Moteur de relances" />
          <CardBody className="flex flex-col gap-3 text-[13px]">
            {relanceConfigQuery.isError ? (
              <ErrorState error={relanceConfigQuery.error} />
            ) : (
              <>
                <div className="flex items-center gap-2">
                  <IconMail size={16} className="text-fg-subtle" />
                  <Badge tone={relanceConfigQuery.data?.mode === 'graph' ? 'green' : 'orange'}>
                    {relanceConfigQuery.data?.mode === 'graph' ? 'Envoi réel' : 'Simulation'}
                  </Badge>
                </div>
                <p className="leading-relaxed text-fg-muted">
                  {relanceConfigQuery.data?.explanation ?? 'Chargement…'}
                </p>
                <dl className="grid grid-cols-2 gap-2 text-fg-muted">
                  <dt>Boîte d'envoi</dt>
                  <dd className="text-fg">{relanceConfigQuery.data?.sender ?? '—'}</dd>
                  <dt>Période de silence</dt>
                  <dd className="text-fg">{relanceConfigQuery.data?.cooldown_days ?? '—'} jours</dd>
                  <dt>Fenêtre « échéance proche »</dt>
                  <dd className="text-fg">{relanceConfigQuery.data?.horizon_days ?? '—'} jours</dd>
                </dl>
              </>
            )}
          </CardBody>
        </Card>

        <Card className="overflow-hidden">
          <CardHeader title="Dernières synchronisations" />
          <DataTable
            columns={syncColumns}
            rows={syncLogsQuery.data?.items ?? []}
            rowKey={(log) => log.id}
            loading={syncLogsQuery.isLoading}
            className="rounded-none border-0"
            empty={
              <EmptyState
                className="rounded-none border-0 border-t border-line"
                icon={<IconRefresh size={40} strokeWidth={1.5} />}
                title="Aucune synchronisation"
                message="Le worker d'ingestion n'a encore traité aucun classeur."
              />
            }
          />
        </Card>
      </div>
    </>
  )
}
