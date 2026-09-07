/**
 * Paramétrage : listes administrables et gabarits de création.
 *
 * Ce qui relevait du code relève d'ici. Ajouter une salle de réunion, renommer
 * une catégorie d'action ou définir le squelette d'un projet type ne demande
 * plus ni migration ni déploiement.
 *
 * Les champs proposés dans l'éditeur de gabarit ne sont pas écrits dans cette
 * page : ils viennent de `GET /gabarits/champs`, qui les lit sur les schémas
 * de création côté serveur. Une liste recopiée ici aurait divergé au premier
 * champ ajouté, et l'écran aurait proposé de préremplir des champs que la
 * création ignore.
 */

import { useMemo, useState, type FormEvent } from 'react'

import { type ApiError } from '@/api/client'
import {
  useChampsGabarit,
  useCreateGabarit,
  useCreateReferentiel,
  useDeleteGabarit,
  useDeleteReferentiel,
  useGabarits,
  useReferentiels,
  useUpdateGabarit,
  useUpdateReferentiel,
} from '@/api/queries'
import {
  GABARIT_ENTITE_LABELS,
  type ChampGabarit,
  type Gabarit,
  type GabaritActionModele,
  type GabaritEntite,
  type Referentiel,
  type ReferentielListe,
  type ReferentielType,
  type RegleChamp,
} from '@/api/types'
import { cn } from '@/lib/cn'
import { Badge } from '@/ui/Badge'
import { Breadcrumb } from '@/ui/Breadcrumb'
import { Button } from '@/ui/Button'
import { Card, CardBody, CardHeader } from '@/ui/Card'
import { EmptyState } from '@/ui/EmptyState'
import { ErrorState } from '@/ui/ErrorState'
import { SelectField, TextAreaField, TextField } from '@/ui/Field'
import { IconGrid, IconPlus, IconTrash } from '@/ui/Icon'
import { Modal } from '@/ui/Modal'
import { PageHeader } from '@/ui/PageHeader'
import { Skeleton } from '@/ui/Skeleton'
import { useToast } from '@/ui/useToast'

type Onglet = 'listes' | 'gabarits'

const ONGLETS: { value: Onglet; label: string }[] = [
  { value: 'listes', label: 'Listes de valeurs' },
  { value: 'gabarits', label: 'Gabarits de création' },
]

export function ParametragePage() {
  const [onglet, setOnglet] = useState<Onglet>('listes')

  return (
    <>
      <Breadcrumb
        items={[{ label: "Vue d'ensemble", to: '/tableau-de-bord' }, { label: 'Paramétrage' }]}
      />
      <PageHeader
        title="Paramétrage"
        description="Listes de valeurs et gabarits — ce qui se personnalise sans toucher au code."
      />

      <div className="mb-6 flex gap-1 border-b border-line" role="tablist">
        {ONGLETS.map((entree) => (
          <button
            key={entree.value}
            type="button"
            role="tab"
            aria-selected={onglet === entree.value}
            onClick={() => setOnglet(entree.value)}
            className={cn(
              '-mb-px border-b-2 px-4 py-2 text-[13px] font-medium transition-colors',
              onglet === entree.value
                ? 'border-accent text-accent'
                : 'border-transparent text-fg-muted hover:text-fg',
            )}
          >
            {entree.label}
          </button>
        ))}
      </div>

      {onglet === 'listes' ? <OngletListes /> : <OngletGabarits />}
    </>
  )
}

/* ------------------------------------------------------------------ */
/* Listes de valeurs                                                   */
/* ------------------------------------------------------------------ */

function OngletListes() {
  // `true` : l'écran d'administration montre aussi les valeurs désactivées,
  // sans quoi on ne pourrait jamais les réactiver.
  const listesQuery = useReferentiels(true)
  const [ajout, setAjout] = useState<ReferentielType | null>(null)

  if (listesQuery.isLoading) return <Skeleton className="h-64 w-full" />
  if (listesQuery.isError)
    return <ErrorState error={listesQuery.error} onRetry={() => void listesQuery.refetch()} />

  return (
    <>
      <div className="grid gap-4 lg:grid-cols-2">
        {(listesQuery.data ?? []).map((liste) => (
          <CarteListe key={liste.type} liste={liste} onAjouter={() => setAjout(liste.type)} />
        ))}
      </div>

      <NouvelleValeurModal type={ajout} onClose={() => setAjout(null)} />
    </>
  )
}

function CarteListe({
  liste,
  onAjouter,
}: {
  liste: ReferentielListe
  onAjouter: () => void
}) {
  return (
    <Card>
      <CardHeader
        title={liste.label}
        description={`${liste.values.length} valeur(s)`}
        actions={
          <Button size="sm" variant="secondary" onClick={onAjouter}>
            <IconPlus size={14} />
            Ajouter
          </Button>
        }
      />
      <CardBody className="p-0">
        {liste.values.length === 0 ? (
          <div className="px-5 py-6">
            <p className="text-[13px] text-fg-subtle">
              Liste vide. Les valeurs ajoutées ici apparaîtront dans les
              formulaires de création.
            </p>
          </div>
        ) : (
          <ul className="divide-y divide-line-subtle">
            {liste.values.map((valeur) => (
              <LigneValeur key={valeur.id} valeur={valeur} />
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  )
}

function LigneValeur({ valeur }: { valeur: Referentiel }) {
  const toast = useToast()
  const update = useUpdateReferentiel()
  const remove = useDeleteReferentiel()

  const basculer = () =>
    update.mutate(
      { id: valeur.id, payload: { is_active: !valeur.is_active } },
      {
        onError: (erreur: ApiError) => toast.error(erreur.message),
      },
    )

  const supprimer = () =>
    remove.mutate(valeur.id, {
      onSuccess: () => toast.success(`« ${valeur.label} » supprimée.`),
      onError: (erreur: ApiError) => toast.error(erreur.message),
    })

  return (
    <li
      className={cn(
        'flex items-center gap-3 px-5 py-2.5',
        !valeur.is_active && 'opacity-55',
      )}
    >
      <span
        aria-hidden="true"
        className="h-3 w-3 shrink-0 rounded-full border border-line"
        style={valeur.color ? { backgroundColor: valeur.color } : undefined}
      />
      <div className="min-w-0 flex-1">
        <p className="truncate text-[13px] font-medium text-fg">{valeur.label}</p>
        <p className="truncate font-mono text-[11px] text-fg-subtle">{valeur.code}</p>
      </div>
      {!valeur.is_active ? <Badge tone="neutral">Inactive</Badge> : null}
      <Button
        size="sm"
        variant="ghost"
        onClick={basculer}
        title={
          valeur.is_active
            ? 'Désactiver : la valeur disparaît des formulaires mais reste lisible sur les objets qui la portent.'
            : 'Réactiver : la valeur redevient proposable à la saisie.'
        }
      >
        {valeur.is_active ? 'Désactiver' : 'Réactiver'}
      </Button>
      <Button
        size="sm"
        variant="ghost"
        onClick={supprimer}
        title="Supprimer définitivement. Préférer la désactivation pour une valeur déjà utilisée."
        aria-label={`Supprimer ${valeur.label}`}
      >
        <IconTrash size={14} />
      </Button>
    </li>
  )
}

function NouvelleValeurModal({
  type,
  onClose,
}: {
  type: ReferentielType | null
  onClose: () => void
}) {
  const toast = useToast()
  const creer = useCreateReferentiel()
  const [label, setLabel] = useState('')
  const [code, setCode] = useState('')
  const [color, setColor] = useState('')
  const [erreur, setErreur] = useState<string | null>(null)

  const fermer = () => {
    setLabel('')
    setCode('')
    setColor('')
    setErreur(null)
    onClose()
  }

  /** Le code est proposé d'après le libellé, et reste modifiable. */
  const codePropose = label
    .normalize('NFD')
    // Échappement explicite des diacritiques combinantes : les écrire
    // littéralement dépend de l'encodage du fichier.
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')

  const soumettre = (event: FormEvent) => {
    event.preventDefault()
    setErreur(null)
    if (type === null) return
    if (!label.trim()) return setErreur('Le libellé est obligatoire.')

    creer.mutate(
      {
        type,
        code: (code.trim() || codePropose).slice(0, 50),
        label: label.trim(),
        color: color.trim() || null,
      },
      {
        onSuccess: (valeur) => {
          toast.success(`« ${valeur.label} » ajoutée.`)
          fermer()
        },
        onError: (apiError: ApiError) => setErreur(apiError.message),
      },
    )
  }

  return (
    <Modal
      open={type !== null}
      onClose={fermer}
      title="Nouvelle valeur"
      footer={
        <>
          <Button size="sm" variant="secondary" onClick={fermer}>
            Annuler
          </Button>
          <Button
            size="sm"
            variant="primary"
            type="submit"
            form="nouvelle-valeur"
            loading={creer.isPending}
          >
            Ajouter
          </Button>
        </>
      }
    >
      <form id="nouvelle-valeur" onSubmit={soumettre} className="flex flex-col gap-4">
        <TextField
          label="Libellé"
          required
          placeholder="Ex : Infrastructure"
          value={label}
          onChange={(event) => setLabel(event.target.value)}
        />
        <TextField
          label="Code"
          placeholder={codePropose || 'infrastructure'}
          hint="Identifiant stable, insensible au renommage du libellé. Laissé vide, il est déduit."
          value={code}
          onChange={(event) => setCode(event.target.value)}
        />
        <TextField
          label="Couleur"
          type="color"
          hint="Sert au badge affiché dans les listes."
          value={color || '#1f4e9c'}
          onChange={(event) => setColor(event.target.value)}
        />
        {erreur ? (
          <p className="rounded-[6px] border border-danger/30 bg-danger-subtle px-3 py-2 text-[13px] font-medium text-danger">
            {erreur}
          </p>
        ) : null}
      </form>
    </Modal>
  )
}

/* ------------------------------------------------------------------ */
/* Gabarits                                                            */
/* ------------------------------------------------------------------ */

function OngletGabarits() {
  const gabaritsQuery = useGabarits(undefined, true)
  const [edite, setEdite] = useState<Gabarit | 'nouveau' | null>(null)

  if (gabaritsQuery.isLoading) return <Skeleton className="h-64 w-full" />
  if (gabaritsQuery.isError)
    return <ErrorState error={gabaritsQuery.error} onRetry={() => void gabaritsQuery.refetch()} />

  const gabarits = gabaritsQuery.data ?? []

  return (
    <>
      <Card>
        <CardHeader
          title="Gabarits"
          description="Valeurs préremplies, champs obligatoires, et actions créées d'office avec un projet."
          actions={
            <Button size="sm" variant="primary" onClick={() => setEdite('nouveau')}>
              <IconPlus size={14} />
              Nouveau gabarit
            </Button>
          }
        />
        <CardBody className="p-0">
          {gabarits.length === 0 ? (
            <div className="p-5">
              <EmptyState
                icon={<IconGrid size={44} strokeWidth={1.5} />}
                title="Aucun gabarit"
                message="Un gabarit préremplit un formulaire de création et peut créer d'office les actions type d'un projet."
                action={
                  <Button size="sm" variant="primary" onClick={() => setEdite('nouveau')}>
                    <IconPlus size={14} />
                    Créer le premier
                  </Button>
                }
              />
            </div>
          ) : (
            <ul className="divide-y divide-line-subtle">
              {gabarits.map((gabarit) => (
                <LigneGabarit
                  key={gabarit.id}
                  gabarit={gabarit}
                  onEditer={() => setEdite(gabarit)}
                />
              ))}
            </ul>
          )}
        </CardBody>
      </Card>

      <GabaritModal
        cible={edite}
        onClose={() => setEdite(null)}
      />
    </>
  )
}

function LigneGabarit({
  gabarit,
  onEditer,
}: {
  gabarit: Gabarit
  onEditer: () => void
}) {
  const toast = useToast()
  const remove = useDeleteGabarit()
  const update = useUpdateGabarit()

  const nbValeurs = Object.keys(gabarit.valeurs).length
  const nbRegles = Object.keys(gabarit.politique).length

  return (
    <li className={cn('flex items-center gap-3 px-5 py-3', !gabarit.is_active && 'opacity-55')}>
      <div className="min-w-0 flex-1">
        <p className="flex items-center gap-2 truncate text-[13px] font-medium text-fg">
          {gabarit.nom}
          <Badge tone={gabarit.entite === 'projet' ? 'blue' : 'purple'}>
            {GABARIT_ENTITE_LABELS[gabarit.entite]}
          </Badge>
          {gabarit.is_default ? <Badge tone="green">Par défaut</Badge> : null}
          {!gabarit.is_active ? <Badge tone="neutral">Inactif</Badge> : null}
        </p>
        <p className="mt-0.5 truncate text-[12px] text-fg-subtle">
          {nbValeurs} valeur(s) préremplie(s) · {nbRegles} règle(s)
          {gabarit.entite === 'projet' ? ` · ${gabarit.actions.length} action(s) type` : ''}
        </p>
      </div>
      <Button
        size="sm"
        variant="ghost"
        onClick={() =>
          update.mutate(
            { id: gabarit.id, payload: { is_active: !gabarit.is_active } },
            { onError: (erreur: ApiError) => toast.error(erreur.message) },
          )
        }
      >
        {gabarit.is_active ? 'Désactiver' : 'Réactiver'}
      </Button>
      <Button size="sm" variant="secondary" onClick={onEditer}>
        Modifier
      </Button>
      <Button
        size="sm"
        variant="ghost"
        aria-label={`Supprimer ${gabarit.nom}`}
        onClick={() =>
          remove.mutate(gabarit.id, {
            onSuccess: () => toast.success(`Gabarit « ${gabarit.nom} » supprimé.`),
            onError: (erreur: ApiError) => toast.error(erreur.message),
          })
        }
      >
        <IconTrash size={14} />
      </Button>
    </li>
  )
}

/* ------------------------------------------------------------------ */
/* Éditeur de gabarit                                                  */
/* ------------------------------------------------------------------ */

/** Valeur brute saisie pour un champ, avant conversion au type attendu. */
type Brouillon = Record<string, string>

function versBrouillon(valeurs: Record<string, unknown>): Brouillon {
  const brouillon: Brouillon = {}
  for (const [champ, valeur] of Object.entries(valeurs)) {
    if (valeur === null || valeur === undefined) continue
    brouillon[champ] = Array.isArray(valeur) ? valeur.join(', ') : String(valeur)
  }
  return brouillon
}

/**
 * Convertit la saisie au type que le serveur attend.
 *
 * Le type vient de `GET /gabarits/champs`, donc du schéma de création
 * lui-même : c'est ce qui évite d'envoyer la chaîne « true » là où un booléen
 * est attendu, et de voir le gabarit refusé à chaque utilisation plutôt qu'à
 * son enregistrement.
 */
function versValeurs(brouillon: Brouillon, champs: ChampGabarit[]): Record<string, unknown> {
  const valeurs: Record<string, unknown> = {}
  for (const champ of champs) {
    const brut = brouillon[champ.nom]
    if (brut === undefined || brut === '') continue
    if (champ.type === 'booleen') valeurs[champ.nom] = brut === 'true'
    else if (champ.type === 'nombre') {
      const nombre = Number(brut)
      if (!Number.isNaN(nombre)) valeurs[champ.nom] = nombre
    } else if (champ.type === 'liste_texte') {
      valeurs[champ.nom] = brut
        .split(',')
        .map((element) => element.trim())
        .filter(Boolean)
    } else valeurs[champ.nom] = brut
  }
  return valeurs
}

function GabaritModal({
  cible,
  onClose,
}: {
  cible: Gabarit | 'nouveau' | null
  onClose: () => void
}) {
  const toast = useToast()
  const champsQuery = useChampsGabarit()
  const referentielsQuery = useReferentiels()
  const creer = useCreateGabarit()
  const modifier = useUpdateGabarit()

  const existant = cible !== null && cible !== 'nouveau' ? cible : null

  // `key` sur le formulaire : changer de gabarit remonte le composant et
  // réinitialise l'état de saisie, sans effet de synchronisation à écrire.
  return (
    <Modal
      open={cible !== null}
      onClose={onClose}
      size="lg"
      title={existant ? `Gabarit « ${existant.nom} »` : 'Nouveau gabarit'}
      footer={
        <>
          <Button size="sm" variant="secondary" onClick={onClose}>
            Annuler
          </Button>
          <Button
            size="sm"
            variant="primary"
            type="submit"
            form="gabarit-form"
            loading={creer.isPending || modifier.isPending}
          >
            Enregistrer
          </Button>
        </>
      }
    >
      {champsQuery.isLoading || referentielsQuery.isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : cible !== null ? (
        <FormulaireGabarit
          key={existant?.id ?? 'nouveau'}
          gabarit={existant}
          champsParEntite={champsQuery.data ?? []}
          listes={referentielsQuery.data ?? []}
          onEnregistrer={(payload) => {
            const suite = {
              onSuccess: () => {
                toast.success('Gabarit enregistré.')
                onClose()
              },
              onError: (erreur: ApiError) => toast.error(erreur.message),
            }
            if (existant) modifier.mutate({ id: existant.id, payload }, suite)
            else creer.mutate({ ...payload, entite: payload.entite ?? 'projet' }, suite)
          }}
        />
      ) : null}
    </Modal>
  )
}

function FormulaireGabarit({
  gabarit,
  champsParEntite,
  listes,
  onEnregistrer,
}: {
  gabarit: Gabarit | null
  champsParEntite: { entite: GabaritEntite; champs: ChampGabarit[] }[]
  listes: ReferentielListe[]
  onEnregistrer: (payload: {
    entite?: GabaritEntite
    nom: string
    description: string | null
    valeurs: Record<string, unknown>
    politique: Record<string, RegleChamp>
    is_default: boolean
    actions: GabaritActionModele[]
  }) => void
}) {
  const [entite, setEntite] = useState<GabaritEntite>(gabarit?.entite ?? 'projet')
  const [nom, setNom] = useState(gabarit?.nom ?? '')
  const [description, setDescription] = useState(gabarit?.description ?? '')
  const [parDefaut, setParDefaut] = useState(gabarit?.is_default ?? false)
  const [brouillon, setBrouillon] = useState<Brouillon>(
    versBrouillon(gabarit?.valeurs ?? {}),
  )
  const [politique, setPolitique] = useState<Record<string, RegleChamp>>(
    gabarit?.politique ?? {},
  )
  const [actions, setActions] = useState<GabaritActionModele[]>(gabarit?.actions ?? [])

  const champs = useMemo(
    () => champsParEntite.find((groupe) => groupe.entite === entite)?.champs ?? [],
    [champsParEntite, entite],
  )

  const valeursListe = (type: ReferentielType | null) =>
    listes.find((liste) => liste.type === type)?.values ?? []

  const basculerRegle = (champ: string, cle: keyof RegleChamp) =>
    setPolitique((precedent) => {
      const regle = { ...(precedent[champ] ?? {}) }
      if (regle[cle]) delete regle[cle]
      else regle[cle] = true
      const suivant = { ...precedent }
      // Une règle vide est retirée : le serveur fait de même, et laisser un
      // objet vide ferait apparaître le champ comme contraint alors qu'il ne
      // l'est plus.
      if (Object.keys(regle).length === 0) delete suivant[champ]
      else suivant[champ] = regle
      return suivant
    })

  const soumettre = (event: FormEvent) => {
    event.preventDefault()
    onEnregistrer({
      entite: gabarit ? undefined : entite,
      nom: nom.trim(),
      description: description.trim() || null,
      valeurs: versValeurs(brouillon, champs),
      politique,
      is_default: parDefaut,
      actions: entite === 'projet' ? actions : [],
    })
  }

  return (
    <form id="gabarit-form" onSubmit={soumettre} className="flex flex-col gap-5">
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField
          label="Nom du gabarit"
          required
          placeholder="Ex : Projet infrastructure"
          value={nom}
          onChange={(event) => setNom(event.target.value)}
        />
        <SelectField
          label="Crée un"
          value={entite}
          // L'entité détermine les champs autorisés : la changer sur un
          // gabarit existant rendrait ses valeurs et sa politique invalides
          // d'un coup. Le serveur la refuse également en modification.
          disabled={gabarit !== null}
          hint={gabarit ? "L'entité d'un gabarit existant ne se change pas." : undefined}
          options={[
            { value: 'projet', label: 'Projet' },
            { value: 'action', label: 'Action' },
          ]}
          onChange={(event) => setEntite(event.target.value as GabaritEntite)}
        />
      </div>

      <TextAreaField
        label="Description"
        rows={2}
        placeholder="À quoi sert ce gabarit, et quand l'utiliser."
        value={description}
        onChange={(event) => setDescription(event.target.value)}
      />

      <label className="flex cursor-pointer items-center gap-2 text-[13px] text-fg">
        <input
          type="checkbox"
          className="h-4 w-4 cursor-pointer accent-accent"
          checked={parDefaut}
          onChange={(event) => setParDefaut(event.target.checked)}
        />
        Proposer ce gabarit d'office
        <span className="text-fg-subtle">— au plus un par type</span>
      </label>

      <div>
        <p className="mb-1 text-[13px] font-medium text-fg">Champs</p>
        <p className="mb-3 text-[12px] text-fg-subtle">
          Une valeur préremplie reste modifiable à la saisie, sauf si vous la
          verrouillez. « Obligatoire » refuse la création tant que le champ est
          vide.
        </p>
        <div className="flex flex-col gap-2">
          {champs.map((champ) => (
            <LigneChamp
              key={champ.nom}
              champ={champ}
              valeur={brouillon[champ.nom] ?? ''}
              regle={politique[champ.nom] ?? {}}
              optionsReferentiel={valeursListe(champ.referentiel)}
              onValeur={(valeur) =>
                setBrouillon((precedent) => ({ ...precedent, [champ.nom]: valeur }))
              }
              onRegle={(cle) => basculerRegle(champ.nom, cle)}
            />
          ))}
        </div>
      </div>

      {entite === 'projet' ? (
        <EditeurActionsType actions={actions} onChange={setActions} />
      ) : null}
    </form>
  )
}

function LigneChamp({
  champ,
  valeur,
  regle,
  optionsReferentiel,
  onValeur,
  onRegle,
}: {
  champ: ChampGabarit
  valeur: string
  regle: RegleChamp
  optionsReferentiel: Referentiel[]
  onValeur: (valeur: string) => void
  onRegle: (cle: keyof RegleChamp) => void
}) {
  const controle = () => {
    if (champ.type === 'booleen')
      return (
        <SelectField
          label={undefined}
          value={valeur}
          options={[
            { value: '', label: '—' },
            { value: 'true', label: 'Oui' },
            { value: 'false', label: 'Non' },
          ]}
          onChange={(event) => onValeur(event.target.value)}
        />
      )
    if (champ.type === 'referentiel')
      return (
        <SelectField
          label={undefined}
          value={valeur}
          options={[
            { value: '', label: '—' },
            ...optionsReferentiel.map((option) => ({
              value: option.id,
              label: option.label,
            })),
          ]}
          onChange={(event) => onValeur(event.target.value)}
        />
      )
    if (champ.type === 'projet')
      // Un gabarit qui fige le projet n'a de sens que pour une action
      // récurrente sur un chantier précis : la saisie reste libre plutôt que
      // de charger la liste complète des projets dans cet écran.
      return (
        <TextField
          label={undefined}
          placeholder="Identifiant du projet"
          value={valeur}
          onChange={(event) => onValeur(event.target.value)}
        />
      )
    return (
      <TextField
        label={undefined}
        type={champ.type === 'nombre' ? 'number' : champ.type === 'date' ? 'date' : 'text'}
        placeholder={champ.type === 'liste_texte' ? 'Andry, Xavier' : '—'}
        value={valeur}
        onChange={(event) => onValeur(event.target.value)}
      />
    )
  }

  return (
    <div className="rounded-[6px] border border-line px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-[140px] flex-1">
          <p className="font-mono text-[12px] font-medium text-fg">{champ.nom}</p>
          {champ.description ? (
            <p className="mt-0.5 line-clamp-2 text-[11px] text-fg-subtle">
              {champ.description}
            </p>
          ) : null}
        </div>
        <div className="min-w-[180px] flex-1">{controle()}</div>
        <div className="flex shrink-0 gap-2.5 text-[12px] text-fg-muted">
          {(['obligatoire', 'verrouille', 'masque'] as const).map((cle) => (
            <label key={cle} className="flex cursor-pointer items-center gap-1">
              <input
                type="checkbox"
                className="h-3.5 w-3.5 cursor-pointer accent-accent"
                checked={Boolean(regle[cle])}
                onChange={() => onRegle(cle)}
              />
              {cle === 'obligatoire' ? 'Oblig.' : cle === 'verrouille' ? 'Verrou.' : 'Masqué'}
            </label>
          ))}
        </div>
      </div>
    </div>
  )
}

function EditeurActionsType({
  actions,
  onChange,
}: {
  actions: GabaritActionModele[]
  onChange: (actions: GabaritActionModele[]) => void
}) {
  const modifier = (index: number, patch: Partial<GabaritActionModele>) =>
    onChange(actions.map((action, i) => (i === index ? { ...action, ...patch } : action)))

  return (
    <div>
      <p className="mb-1 text-[13px] font-medium text-fg">Actions type</p>
      <p className="mb-3 text-[12px] text-fg-subtle">
        Créées d'office avec le projet. L'échéance est exprimée en jours à
        partir de la création — une date fixe serait périmée dès le deuxième
        usage du gabarit.
      </p>

      <div className="flex flex-col gap-2">
        {actions.map((action, index) => (
          <div
            key={index}
            className="flex flex-wrap items-end gap-2 rounded-[6px] border border-line px-3 py-2.5"
          >
            <TextField
              className="min-w-[200px] flex-1"
              label={index === 0 ? 'Intitulé' : undefined}
              value={action.description}
              onChange={(event) => modifier(index, { description: event.target.value })}
            />
            <TextField
              className="w-28"
              label={index === 0 ? 'J+' : undefined}
              type="number"
              min={0}
              value={action.delai_jours ?? ''}
              onChange={(event) =>
                modifier(index, {
                  delai_jours: event.target.value === '' ? null : Number(event.target.value),
                })
              }
            />
            <TextField
              className="w-44"
              label={index === 0 ? 'Responsables' : undefined}
              placeholder="Andry, Xavier"
              value={action.responsable_names.join(', ')}
              onChange={(event) =>
                modifier(index, {
                  responsable_names: event.target.value
                    .split(',')
                    .map((nom) => nom.trim())
                    .filter(Boolean),
                })
              }
            />
            <Button
              size="sm"
              variant="ghost"
              aria-label="Retirer cette action"
              onClick={() => onChange(actions.filter((_, i) => i !== index))}
            >
              <IconTrash size={14} />
            </Button>
          </div>
        ))}
      </div>

      <Button
        size="sm"
        variant="secondary"
        className="mt-2"
        onClick={() =>
          onChange([
            ...actions,
            {
              description: '',
              position: actions.length,
              responsable_names: [],
              delai_jours: null,
            },
          ])
        }
      >
        <IconPlus size={14} />
        Ajouter une action type
      </Button>
    </div>
  )
}
