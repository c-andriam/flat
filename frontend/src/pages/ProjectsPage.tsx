import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import { type ApiError } from '@/api/client'
import { useCreateProject, useProjects } from '@/api/queries'
import type { Project } from '@/api/types'
import { useAuth } from '@/auth/useAuth'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { formatDateTime } from '@/lib/date'
import { Badge } from '@/ui/Badge'
import { Breadcrumb } from '@/ui/Breadcrumb'
import { Button } from '@/ui/Button'
import { DataTable, type Column } from '@/ui/DataTable'
import { EmptyState } from '@/ui/EmptyState'
import { ErrorState } from '@/ui/ErrorState'
import { SelectField, TextField } from '@/ui/Field'
import { IconFolder, IconPlus, IconSearch } from '@/ui/Icon'
import { Modal } from '@/ui/Modal'
import { PageHeader } from '@/ui/PageHeader'
import { Pagination } from '@/ui/Pagination'
import { useToast } from '@/ui/useToast'

type ScopeFilter = 'active' | 'archived' | 'all'

const SCOPE_OPTIONS = [
  { value: 'active', label: 'Projets actifs' },
  { value: 'archived', label: 'Projets archivés' },
  { value: 'all', label: 'Tous les projets' },
] as const

const PAGE_SIZE = 25

export function ProjectsPage() {
  const { canWrite } = useAuth()
  const [scope, setScope] = useState<ScopeFilter>('active')
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const [modalOpen, setModalOpen] = useState(false)
  const debouncedSearch = useDebouncedValue(search, 250)

  const projectsQuery = useProjects({
    is_active: scope === 'all' ? null : scope === 'active',
    limit: PAGE_SIZE,
    offset,
  })

  // L'API ne propose pas de recherche texte sur les projets : le filtre est
  // appliqué sur la page courante, ce que la mention sous le champ indique.
  const needle = debouncedSearch.trim().toLowerCase()
  const rows = (projectsQuery.data?.items ?? []).filter(
    (project) =>
      !needle ||
      project.code.toLowerCase().includes(needle) ||
      project.name.toLowerCase().includes(needle),
  )

  const columns: Column<Project>[] = [
    {
      key: 'code',
      header: 'Code',
      render: (project) => (
        <Link
          to={`/projets/${project.id}`}
          className="font-semibold text-accent no-underline hover:underline"
        >
          {project.code}
        </Link>
      ),
      className: 'w-28',
    },
    {
      key: 'name',
      header: 'Intitulé',
      render: (project) => <span className="line-clamp-1 text-fg">{project.name}</span>,
    },
    {
      key: 'phases',
      header: 'Phases',
      render: (project) =>
        project.has_phases ? <Badge tone="purple">Par phases</Badge> : <span className="text-fg-subtle">—</span>,
      className: 'w-32',
      hideOnMobile: true,
    },
    {
      key: 'sync',
      header: 'Dernière synchro',
      render: (project) => (
        <span className="whitespace-nowrap text-fg-muted">
          {formatDateTime(project.last_synced_at)}
        </span>
      ),
      className: 'w-48',
      hideOnMobile: true,
    },
    {
      key: 'status',
      header: 'État',
      render: (project) =>
        project.is_active ? <Badge tone="green">Actif</Badge> : <Badge tone="neutral">Archivé</Badge>,
      className: 'w-28',
    },
  ]

  return (
    <>
      <Breadcrumb items={[{ label: "Vue d'ensemble", to: '/tableau-de-bord' }, { label: 'Projets' }]} />
      <PageHeader
        title="Projets"
        description="Portefeuille suivi, synchronisé depuis les classeurs SharePoint."
        actions={
          canWrite ? (
            <Button size="sm" variant="primary" onClick={() => setModalOpen(true)}>
              <IconPlus size={14} />
              Nouveau projet
            </Button>
          ) : null
        }
      />

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <TextField
          className="min-w-[220px] flex-1"
          label="Rechercher"
          placeholder="Code ou intitulé…"
          hint="Filtre appliqué sur la page affichée."
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <SelectField
          className="w-52"
          label="Périmètre"
          value={scope}
          onChange={(event) => {
            setScope(event.target.value as ScopeFilter)
            setOffset(0)
          }}
          options={SCOPE_OPTIONS}
        />
      </div>

      {projectsQuery.isError ? (
        <ErrorState error={projectsQuery.error} onRetry={() => void projectsQuery.refetch()} />
      ) : (
        <>
          <DataTable
            columns={columns}
            rows={rows}
            rowKey={(project) => project.id}
            loading={projectsQuery.isLoading}
            empty={
              <EmptyState
                icon={needle ? <IconSearch size={44} strokeWidth={1.5} /> : <IconFolder size={44} strokeWidth={1.5} />}
                title={needle ? 'Aucun projet ne correspond' : 'Aucun projet trouvé'}
                message={
                  needle
                    ? 'Essayez un autre code ou changez de périmètre.'
                    : 'Commencez par créer un projet pour centraliser vos données.'
                }
                action={
                  canWrite && !needle ? (
                    <Button size="sm" variant="primary" onClick={() => setModalOpen(true)}>
                      <IconPlus size={14} />
                      Nouveau projet
                    </Button>
                  ) : undefined
                }
              />
            }
          />
          <Pagination
            total={projectsQuery.data?.total ?? 0}
            limit={PAGE_SIZE}
            offset={offset}
            onOffsetChange={setOffset}
          />
        </>
      )}

      <NewProjectModal open={modalOpen} onClose={() => setModalOpen(false)} />
    </>
  )
}

function NewProjectModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const toast = useToast()
  const createProject = useCreateProject()
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [sourcePath, setSourcePath] = useState('')
  const [hasPhases, setHasPhases] = useState('false')
  const [error, setError] = useState<string | null>(null)

  const reset = () => {
    setCode('')
    setName('')
    setSourcePath('')
    setHasPhases('false')
    setError(null)
  }

  const close = () => {
    reset()
    onClose()
  }

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    if (!code.trim()) return setError('Le code projet est obligatoire.')
    if (!name.trim()) return setError("L'intitulé est obligatoire.")
    if (!sourcePath.trim()) return setError('Le chemin du fichier source est obligatoire.')

    createProject.mutate(
      {
        code: code.trim(),
        name: name.trim(),
        source_file_path: sourcePath.trim(),
        has_phases: hasPhases === 'true',
      },
      {
        onSuccess: (project) => {
          toast.success(`Projet ${project.code} créé.`)
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
      title="Nouveau projet"
      footer={
        <>
          <Button size="sm" variant="secondary" onClick={close}>
            Annuler
          </Button>
          <Button
            size="sm"
            variant="primary"
            type="submit"
            form="new-project-form"
            loading={createProject.isPending}
          >
            Créer le projet
          </Button>
        </>
      }
    >
      <form id="new-project-form" onSubmit={onSubmit} className="flex flex-col gap-4">
        <TextField
          label="Code projet"
          required
          placeholder="Ex : P01"
          value={code}
          onChange={(event) => setCode(event.target.value)}
        />
        <TextField
          label="Intitulé"
          required
          placeholder="Ex : Refonte du système de facturation"
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
        <TextField
          label="Fichier source"
          required
          placeholder="Ex : /Documents partages/Suivi/P01.xlsx"
          hint="Chemin SharePoint du classeur de suivi utilisé à l'ingestion."
          value={sourcePath}
          onChange={(event) => setSourcePath(event.target.value)}
        />
        <SelectField
          label="Numérotation"
          hint="Par phases, les actions sont numérotées P01-02-05 et la phase devient obligatoire."
          value={hasPhases}
          onChange={(event) => setHasPhases(event.target.value)}
          options={[
            { value: 'false', label: 'Numérotation simple' },
            { value: 'true', label: 'Numérotation par phases' },
          ]}
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
