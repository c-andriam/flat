import { useEffect, useState, type FormEvent } from 'react'

import { type ApiError } from '@/api/client'
import { useCreateAction, useProjects } from '@/api/queries'
import type { Project, Uuid } from '@/api/types'
import { Button } from '@/ui/Button'
import { SelectField, TextAreaField, TextField } from '@/ui/Field'
import { Modal } from '@/ui/Modal'
import { useToast } from '@/ui/useToast'

interface Props {
  open: boolean
  onClose: () => void
  /** Pré-sélection depuis la fiche d'un projet. */
  defaultProjectId?: Uuid
}

interface FormState {
  project_id: string
  description: string
  resp_suivi: string
  responsables: string
  deadline: string
  phase: string
  charges_hj: string
  commentaire: string
}

const EMPTY: FormState = {
  project_id: '',
  description: '',
  resp_suivi: '',
  responsables: '',
  deadline: '',
  phase: '',
  charges_hj: '',
  commentaire: '',
}

export function NewActionModal({ open, onClose, defaultProjectId }: Props) {
  const toast = useToast()
  const projectsQuery = useProjects({ is_active: true, limit: 200 })
  const createAction = useCreateAction()
  const [form, setForm] = useState<FormState>(EMPTY)
  const [formError, setFormError] = useState<string | null>(null)

  const projects: Project[] = projectsQuery.data?.items ?? []
  const selectedProject = projects.find((project) => project.id === form.project_id)

  useEffect(() => {
    if (!open) {
      setForm(EMPTY)
      setFormError(null)
      return
    }
    setForm((current) => ({
      ...current,
      project_id: defaultProjectId ?? (current.project_id || projects[0]?.id || ''),
    }))
    // `projects` change à chaque rafraîchissement du cache : ne dépendre que
    // du premier identifiant évite de réinitialiser le formulaire en cours de saisie.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, defaultProjectId, projects[0]?.id])

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((current) => ({ ...current, [key]: value }))

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    setFormError(null)

    const responsableNames = form.responsables
      .split(',')
      .map((name) => name.trim())
      .filter(Boolean)

    if (!form.project_id) return setFormError('Sélectionnez un projet.')
    if (!form.description.trim()) return setFormError('La description est obligatoire.')
    if (!form.resp_suivi.trim()) return setFormError('Le responsable du suivi est obligatoire.')
    if (!form.deadline) return setFormError("L'échéance est obligatoire.")
    if (responsableNames.length === 0)
      return setFormError('Indiquez au moins un responsable de réalisation.')
    if (selectedProject?.has_phases && !form.phase.trim())
      return setFormError('Ce projet est géré par phases : renseignez la phase.')

    const charges = form.charges_hj.trim() === '' ? null : Number(form.charges_hj)
    if (charges !== null && !Number.isFinite(charges))
      return setFormError('Les charges doivent être un nombre.')

    createAction.mutate(
      {
        project_id: form.project_id,
        description: form.description.trim(),
        resp_suivi: form.resp_suivi.trim(),
        deadline: form.deadline,
        responsable_names: responsableNames,
        phase: form.phase.trim() || null,
        charges_hj: charges,
        commentaire: form.commentaire.trim() || null,
      },
      {
        onSuccess: (action) => {
          toast.success(`Action ${action.numero} créée.`)
          onClose()
        },
        onError: (error: ApiError) => setFormError(error.message),
      },
    )
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Nouvelle action"
      size="lg"
      footer={
        <>
          <Button size="sm" variant="secondary" onClick={onClose}>
            Annuler
          </Button>
          <Button
            size="sm"
            variant="primary"
            form="new-action-form"
            type="submit"
            loading={createAction.isPending}
          >
            Créer l'action
          </Button>
        </>
      }
    >
      <form id="new-action-form" onSubmit={onSubmit} className="flex flex-col gap-4">
        <SelectField
          label="Projet"
          required
          value={form.project_id}
          onChange={(event) => update('project_id', event.target.value)}
          options={[
            { value: '', label: projectsQuery.isLoading ? 'Chargement…' : 'Sélectionner un projet' },
            ...projects.map((project) => ({
              value: project.id,
              label: `${project.code} — ${project.name}`,
            })),
          ]}
        />

        <TextAreaField
          label="Description"
          required
          placeholder="Ex : Mise à jour des serveurs de préproduction"
          value={form.description}
          onChange={(event) => update('description', event.target.value)}
        />

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <TextField
            label="Responsable du suivi"
            required
            placeholder="Ex : Meylis"
            value={form.resp_suivi}
            onChange={(event) => update('resp_suivi', event.target.value)}
          />
          <TextField
            label="Échéance"
            type="date"
            required
            value={form.deadline}
            onChange={(event) => update('deadline', event.target.value)}
          />
        </div>

        <TextField
          label="Responsables de réalisation"
          required
          placeholder="Ex : Andry, Xavier"
          hint="Un nom par entrée, séparés par des virgules — l'API refuse les noms composés."
          value={form.responsables}
          onChange={(event) => update('responsables', event.target.value)}
        />

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <TextField
            label="Phase"
            placeholder={selectedProject?.has_phases ? 'Ex : 02' : 'Non applicable'}
            disabled={!selectedProject?.has_phases}
            hint={
              selectedProject?.has_phases
                ? 'Obligatoire : ce projet numérote ses actions par phase.'
                : 'Ce projet ne gère pas de phases.'
            }
            value={form.phase}
            onChange={(event) => update('phase', event.target.value)}
          />
          <TextField
            label="Charges estimées (h/j)"
            type="number"
            min={0}
            step="0.5"
            placeholder="Ex : 2.5"
            value={form.charges_hj}
            onChange={(event) => update('charges_hj', event.target.value)}
          />
        </div>

        <TextAreaField
          label="Commentaire"
          rows={2}
          placeholder="Contexte, dépendances, points d'attention…"
          value={form.commentaire}
          onChange={(event) => update('commentaire', event.target.value)}
        />

        {formError ? (
          <p className="rounded-[6px] border border-danger/30 bg-danger-subtle px-3 py-2 text-[13px] font-medium text-danger">
            {formError}
          </p>
        ) : null}
      </form>
    </Modal>
  )
}
