/**
 * Hooks de lecture et de mutation.
 *
 * Chaque mutation invalide les racines de cache concernées plutôt qu'une clé
 * précise : une action modifiée change aussi les compteurs du tableau de bord
 * et les rapports du projet, qu'un `setQueryData` ciblé laisserait périmés.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type QueryKey,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query'

import { type ApiError } from './client'
import {
  patcherEntite,
  patcherObjet,
  retirerEntite,
  type Rollback,
} from './optimistic'
import {
  actions as actionsApi,
  gabarits as gabaritsApi,
  logs as logsApi,
  referentiels as referentielsApi,
  projects as projectsApi,
  relances as relancesApi,
  reports as reportsApi,
  dailyReports as dailyReportsApi,
  responsables as responsablesApi,
  slots as slotsApi,
  users as usersApi,
  type ActionListParams,
  type ProjectListParams,
  type ResponsableListParams,
  type SlotWindowParams,
} from './endpoints'
import { queryKeys } from './queryKeys'
import type {
  Action,
  ActionCreate,
  ChampsGabarit,
  Gabarit,
  GabaritCreate,
  GabaritEntite,
  GabaritUpdate,
  ActionSummary,
  ActionUpdate,
  ForecastReport,
  Page,
  PortfolioReport,
  Project,
  ProjectCreate,
  ProjectReport,
  ProjectUpdate,
  ProjectWithActions,
  Referentiel,
  ReferentielCreate,
  ReferentielListe,
  ReferentielUpdate,
  RelanceBatch,
  RelanceConfig,
  RelanceDigestBatch,
  RelanceDigestPreview,
  RelanceDigestSendResult,
  RelanceKind,
  RelanceLog,
  RelancePreference,
  RelancePreferenceUpdate,
  Responsable,
  ResponsableCreate,
  ResponsableUpdate,
  SyncLog,
  User,
  UserUpdate,
  Uuid,
  WorkloadReport,
  Slot,
  SlotOpenPayload,
  SlotOpenResult,
  SlotOwner,
  SlotRequest,
  SlotRequestPayload,
  SlotMovePayload,
  SlotStatus,
  DailyReport,
  DailyReportPayload,
  TodayReport,
} from './types'

type Query<T> = UseQueryResult<T, ApiError>
/**
 * `TContext` porte ce que `onMutate` a renvoyé — le rollback d'une mise à jour
 * optimiste. Sans ce paramètre, il valait `unknown` et `onError` ne pouvait
 * pas s'en servir pour restaurer l'état d'avant.
 */
type Mutation<TData, TVars, TContext = unknown> = UseMutationResult<
  TData,
  ApiError,
  TVars,
  TContext
>

// ─── Projets ───

export function useProjects(params: ProjectListParams = {}): Query<Page<Project>> {
  return useQuery({
    queryKey: queryKeys.projects.list(params),
    queryFn: ({ signal }) => projectsApi.list(params, signal),
  })
}

export function useProject(id: Uuid | undefined): Query<ProjectWithActions> {
  return useQuery({
    queryKey: queryKeys.projects.detail(id ?? ''),
    queryFn: ({ signal }) => projectsApi.get(id as Uuid, signal),
    enabled: Boolean(id),
  })
}

export function useCreateProject(): Mutation<Project, ProjectCreate> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: ProjectCreate) => projectsApi.create(payload),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.projects.all })
      void client.invalidateQueries({ queryKey: queryKeys.reports.all })
    },
  })
}

export function useUpdateProject(): Mutation<
  Project,
  { id: Uuid; payload: ProjectUpdate },
  Rollback
> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, payload }: { id: Uuid; payload: ProjectUpdate }) =>
      projectsApi.update(id, payload),
    onMutate: ({ id, payload }) =>
      patcherEntite<Project>(
        client,
        queryKeys.projects.all,
        id,
        payload as Partial<Project>,
      ),
    onError: (_erreur, _variables, rollback) => rollback?.restaurer(),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: queryKeys.projects.all })
      void client.invalidateQueries({ queryKey: queryKeys.reports.all })
    },
  })
}

export function useDeleteProject(): Mutation<void, Uuid> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: Uuid) => projectsApi.remove(id),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.projects.all })
      void client.invalidateQueries({ queryKey: queryKeys.actions.all })
      void client.invalidateQueries({ queryKey: queryKeys.reports.all })
    },
  })
}

// ─── Actions ───

export function useActions(params: ActionListParams = {}): Query<Page<Action>> {
  return useQuery({
    queryKey: queryKeys.actions.list(params),
    queryFn: ({ signal }) => actionsApi.list(params, signal),
    // Garder la page précédente visible pendant un changement de filtre évite
    // que le tableau ne « saute » entre squelette et données à chaque frappe.
    placeholderData: (previous) => previous,
  })
}

export function useAction(id: Uuid | undefined): Query<Action> {
  return useQuery({
    queryKey: queryKeys.actions.detail(id ?? ''),
    queryFn: ({ signal }) => actionsApi.get(id as Uuid, signal),
    enabled: Boolean(id),
  })
}

export function useActionSummary(): Query<ActionSummary> {
  return useQuery({
    queryKey: queryKeys.actions.summary,
    queryFn: ({ signal }) => actionsApi.summary(signal),
  })
}

export function useCreateAction(): Mutation<Action, ActionCreate> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: ActionCreate) => actionsApi.create(payload),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.actions.all })
      void client.invalidateQueries({ queryKey: queryKeys.projects.all })
      void client.invalidateQueries({ queryKey: queryKeys.reports.all })
    },
  })
}

/**
 * Modifie une action, en affichant le changement avant la réponse du serveur.
 *
 * La bascule « en veille » et l'avancement se modifient d'un clic depuis une
 * liste : attendre l'aller-retour (~250 ms vers Supabase) donne un bouton qui
 * ne réagit pas, et un utilisateur qui reclique. Le cache est donc modifié
 * tout de suite, puis restauré si le serveur refuse.
 */
export function useUpdateAction(): Mutation<
  Action,
  { id: Uuid; payload: ActionUpdate },
  Rollback
> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, payload }: { id: Uuid; payload: ActionUpdate }) =>
      actionsApi.update(id, payload),

    onMutate: ({ id, payload }) =>
      patcherEntite<Action>(client, queryKeys.actions.all, id, payload as Partial<Action>),

    // Le serveur a refusé : on remet exactement ce qui était affiché avant.
    // C'est le composant appelant qui annonce l'échec — lui seul sait quoi
    // dire à l'utilisateur.
    onError: (_erreur, _variables, rollback) => rollback?.restaurer(),

    // `onSettled` et non `onSuccess` : après un échec aussi, il faut relire.
    // Le serveur peut avoir appliqué une partie du changement, ou en avoir
    // déduit d'autres — passer `progress` à 100 bascule le statut.
    onSettled: () => {
      void client.invalidateQueries({ queryKey: queryKeys.actions.all })
      void client.invalidateQueries({ queryKey: queryKeys.reports.all })
    },
  })
}

export function useDeleteAction(): Mutation<void, Uuid> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: Uuid) => actionsApi.remove(id),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.actions.all })
      void client.invalidateQueries({ queryKey: queryKeys.reports.all })
    },
  })
}

// ─── Responsables ───

export function useResponsables(params: ResponsableListParams = {}): Query<Page<Responsable>> {
  return useQuery({
    queryKey: queryKeys.responsables.list(params),
    queryFn: ({ signal }) => responsablesApi.list(params, signal),
    placeholderData: (previous) => previous,
  })
}

export function useCreateResponsable(): Mutation<Responsable, ResponsableCreate> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: ResponsableCreate) => responsablesApi.create(payload),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.responsables.all })
      void client.invalidateQueries({ queryKey: queryKeys.reports.all })
    },
  })
}

export function useUpdateResponsable(): Mutation<
  Responsable,
  { id: Uuid; payload: ResponsableUpdate }
> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, payload }: { id: Uuid; payload: ResponsableUpdate }) =>
      responsablesApi.update(id, payload),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.responsables.all })
      void client.invalidateQueries({ queryKey: queryKeys.actions.all })
      void client.invalidateQueries({ queryKey: queryKeys.reports.all })
    },
  })
}

export function useDeleteResponsable(): Mutation<void, Uuid> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: Uuid) => responsablesApi.remove(id),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.responsables.all })
      void client.invalidateQueries({ queryKey: queryKeys.actions.all })
      void client.invalidateQueries({ queryKey: queryKeys.reports.all })
    },
  })
}

// ─── Rapports ───

export function usePortfolioReport(scope: 'active' | 'all' = 'active'): Query<PortfolioReport> {
  return useQuery({
    queryKey: queryKeys.reports.portfolio(scope),
    queryFn: ({ signal }) => reportsApi.portfolio(scope, signal),
  })
}

export function useProjectReport(id: Uuid | undefined): Query<ProjectReport> {
  return useQuery({
    queryKey: queryKeys.reports.project(id ?? ''),
    queryFn: ({ signal }) => reportsApi.project(id as Uuid, signal),
    enabled: Boolean(id),
  })
}

export function useWorkloadReport(activeProjectsOnly = true): Query<WorkloadReport> {
  return useQuery({
    queryKey: queryKeys.reports.workload(activeProjectsOnly),
    queryFn: ({ signal }) => reportsApi.workload(activeProjectsOnly, signal),
  })
}

export interface ForecastParams {
  weeks?: number
  start_offset?: number
  include_actions?: boolean
  active_projects_only?: boolean
}

export function useForecastReport(params: ForecastParams = {}): Query<ForecastReport> {
  return useQuery({
    queryKey: queryKeys.reports.forecast(params),
    queryFn: ({ signal }) => reportsApi.forecast(params, signal),
  })
}

// ─── Relances ───

/**
 * `enabled` n'est pas décoratif : la route est réservée aux comptes en
 * écriture, et l'appeler depuis un compte lecteur produit un 403 à chaque
 * affichage de la page — une erreur dans la console pour une information
 * qu'on ne comptait de toute façon pas montrer.
 */
export function useRelanceConfig(enabled = true): Query<RelanceConfig> {
  return useQuery({
    queryKey: queryKeys.relances.config,
    queryFn: ({ signal }) => relancesApi.config(signal),
    // La configuration d'envoi ne change qu'au redémarrage d'un conteneur.
    staleTime: 5 * 60_000,
    enabled,
  })
}

export function useSendRelanceBatch(): Mutation<RelanceBatch, RelanceKind> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (kind: RelanceKind) => relancesApi.sendBatch(kind),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.relances.all })
      void client.invalidateQueries({ queryKey: ['logs'] })
    },
  })
}

/** Réglages du compte connecté. */
export function useMyRelancePreference(): Query<RelancePreference> {
  return useQuery({
    queryKey: queryKeys.relances.myPreference,
    queryFn: ({ signal }) => relancesApi.myPreference(signal),
    // Un compte sans fiche responsable rattachée reçoit un 404 : c'est une
    // réponse définitive, pas une panne passagère. Réessayer afficherait un
    // spinner pendant plusieurs secondes avant le même message.
    retry: false,
  })
}

export function useUpdateMyRelancePreference(): Mutation<
  RelancePreference,
  RelancePreferenceUpdate,
  Rollback
> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: RelancePreferenceUpdate) =>
      relancesApi.updateMyPreference(payload),

    // Ce formulaire se règle case par case et jour par jour : chaque clic
    // enregistre. Attendre la réponse rendait les cases molles, au point
    // qu'on doutait d'avoir cliqué.
    onMutate: (payload) =>
      patcherObjet<RelancePreference>(
        client,
        queryKeys.relances.myPreference,
        payload as Partial<RelancePreference>,
      ),
    onError: (_erreur, _variables, rollback) => rollback?.restaurer(),

    onSuccess: (preference) => {
      // La réponse porte les réglages *effectifs* : la cadence en clair et la
      // fréquence hebdomadaire sont recalculées par le serveur, la mise à
      // jour optimiste ne pouvait pas les deviner.
      client.setQueryData(queryKeys.relances.myPreference, preference)
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: queryKeys.relances.all })
    },
  })
}

/** Réglages de toute l'équipe — réservé aux administrateurs. */
export function useRelancePreferences(
  tous = false,
  enabled = true,
): Query<RelancePreference[]> {
  return useQuery({
    queryKey: queryKeys.relances.preferences(tous),
    queryFn: ({ signal }) => relancesApi.preferences(tous, signal),
    enabled,
  })
}

export function useUpdateRelancePreference(): Mutation<
  RelancePreference,
  { responsableId: Uuid; payload: RelancePreferenceUpdate },
  Rollback
> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ responsableId, payload }) =>
      relancesApi.updatePreference(responsableId, payload),
    // Le tableau de l'équipe est indexé par `responsable_id`, pas par `id` :
    // une préférence n'a pas d'existence propre en dehors de la personne
    // qu'elle concerne.
    onMutate: ({ responsableId, payload }) =>
      patcherEntite<RelancePreference>(
        client,
        queryKeys.relances.all,
        responsableId,
        payload as Partial<RelancePreference>,
        'responsable_id',
      ),
    onError: (_erreur, _variables, rollback) => rollback?.restaurer(),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: queryKeys.relances.all })
    },
  })
}

/** Aperçu du récapitulatif d'une personne. */
export function useRelanceDigest(
  responsableId: Uuid | null,
): Query<RelanceDigestPreview> {
  return useQuery({
    queryKey: queryKeys.relances.digest(responsableId ?? 'aucun'),
    queryFn: ({ signal }) => relancesApi.digest(responsableId as Uuid, signal),
    enabled: responsableId !== null,
  })
}

export function useSendRelanceDigest(): Mutation<RelanceDigestSendResult, Uuid> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (responsableId: Uuid) => relancesApi.sendDigest(responsableId),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.relances.all })
      void client.invalidateQueries({ queryKey: ['logs'] })
    },
  })
}

export function useSendRelanceDigestBatch(): Mutation<RelanceDigestBatch, boolean> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (dryRun: boolean) => relancesApi.sendDigestBatch(dryRun),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.relances.all })
      void client.invalidateQueries({ queryKey: ['logs'] })
    },
  })
}

// ─── Paramétrage : référentiels ───

/**
 * Toutes les listes administrables en un appel.
 *
 * `staleTime` long : ce sont des listes de paramétrage, elles changent
 * quelques fois par an. Les relire à chaque ouverture de formulaire aurait
 * ajouté un aller-retour à chaque création.
 */
export function useReferentiels(inclureInactifs = false): Query<ReferentielListe[]> {
  return useQuery({
    queryKey: queryKeys.referentiels.list(inclureInactifs),
    queryFn: ({ signal }) => referentielsApi.list(inclureInactifs, signal),
    staleTime: 5 * 60_000,
  })
}

export function useCreateReferentiel(): Mutation<Referentiel, ReferentielCreate> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: ReferentielCreate) => referentielsApi.create(payload),
    // Pas de création optimiste : l'identifiant vient du serveur, et une
    // ligne fantôme sans identifiant ne serait ni modifiable ni supprimable
    // tant que la réponse n'est pas là.
    onSettled: () => {
      void client.invalidateQueries({ queryKey: queryKeys.referentiels.all })
    },
  })
}

export function useUpdateReferentiel(): Mutation<
  Referentiel,
  { id: Uuid; payload: ReferentielUpdate },
  Rollback
> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, payload }: { id: Uuid; payload: ReferentielUpdate }) =>
      referentielsApi.update(id, payload),
    onMutate: ({ id, payload }) =>
      patcherEntite<Referentiel>(
        client,
        queryKeys.referentiels.all,
        id,
        payload as Partial<Referentiel>,
      ),
    onError: (_erreur, _variables, rollback) => rollback?.restaurer(),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: queryKeys.referentiels.all })
      // Le libellé et la couleur sont affichés sur les projets et actions.
      void client.invalidateQueries({ queryKey: queryKeys.projects.all })
      void client.invalidateQueries({ queryKey: queryKeys.actions.all })
    },
  })
}

export function useDeleteReferentiel(): Mutation<void, Uuid, Rollback> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: Uuid) => referentielsApi.remove(id),
    onMutate: (id) => retirerEntite(client, queryKeys.referentiels.all, id),
    onError: (_erreur, _variables, rollback) => rollback?.restaurer(),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: queryKeys.referentiels.all })
    },
  })
}

// ─── Paramétrage : gabarits ───

export function useGabarits(
  entite?: GabaritEntite,
  inclureInactifs = false,
): Query<Gabarit[]> {
  const params = { entite: entite ?? null, inclure_inactifs: inclureInactifs }
  return useQuery({
    queryKey: queryKeys.gabarits.list(params),
    queryFn: ({ signal }) => gabaritsApi.list(params, signal),
    staleTime: 5 * 60_000,
  })
}

/** Champs préremplissables, lus sur les schémas de création côté serveur. */
export function useChampsGabarit(): Query<ChampsGabarit[]> {
  return useQuery({
    queryKey: queryKeys.gabarits.champs,
    queryFn: ({ signal }) => gabaritsApi.champs(signal),
    // Ils ne changent qu'avec une version de l'application.
    staleTime: Infinity,
  })
}

export function useCreateGabarit(): Mutation<Gabarit, GabaritCreate> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: GabaritCreate) => gabaritsApi.create(payload),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: queryKeys.gabarits.all })
    },
  })
}

export function useUpdateGabarit(): Mutation<
  Gabarit,
  { id: Uuid; payload: GabaritUpdate },
  Rollback
> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, payload }: { id: Uuid; payload: GabaritUpdate }) =>
      gabaritsApi.update(id, payload),
    onMutate: ({ id, payload }) =>
      patcherEntite<Gabarit>(
        client,
        queryKeys.gabarits.all,
        id,
        payload as Partial<Gabarit>,
      ),
    onError: (_erreur, _variables, rollback) => rollback?.restaurer(),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: queryKeys.gabarits.all })
    },
  })
}

export function useDeleteGabarit(): Mutation<void, Uuid, Rollback> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: Uuid) => gabaritsApi.remove(id),
    onMutate: (id) => retirerEntite(client, queryKeys.gabarits.all, id),
    onError: (_erreur, _variables, rollback) => rollback?.restaurer(),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: queryKeys.gabarits.all })
    },
  })
}

/** Crée un projet depuis un gabarit, actions type comprises. */
export function useCreateProjectFromGabarit(): Mutation<
  ProjectWithActions,
  { gabaritId: Uuid; payload: Partial<ProjectCreate> }
> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ gabaritId, payload }) => gabaritsApi.creerProjet(gabaritId, payload),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: queryKeys.projects.all })
      // Le gabarit a créé des actions : les compteurs et les rapports
      // changent aussi.
      void client.invalidateQueries({ queryKey: queryKeys.actions.all })
      void client.invalidateQueries({ queryKey: queryKeys.reports.all })
    },
  })
}

export function useCreateActionFromGabarit(): Mutation<
  Action,
  { gabaritId: Uuid; payload: Partial<ActionCreate> }
> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ gabaritId, payload }) => gabaritsApi.creerAction(gabaritId, payload),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: queryKeys.actions.all })
      void client.invalidateQueries({ queryKey: queryKeys.projects.all })
      void client.invalidateQueries({ queryKey: queryKeys.reports.all })
    },
  })
}

// ─── Journaux ───

export function useSyncLogs(limit = 20): Query<Page<SyncLog>> {
  return useQuery({
    queryKey: queryKeys.logs.sync(limit),
    queryFn: ({ signal }) => logsApi.sync(limit, signal),
  })
}

export function useRelanceLogs(limit = 20): Query<Page<RelanceLog>> {
  return useQuery({
    queryKey: queryKeys.logs.relances(limit),
    queryFn: ({ signal }) => logsApi.relances(limit, signal),
  })
}

// ─── Utilisateurs ───

export function useUsers(enabled = true): Query<Page<User>> {
  return useQuery({
    queryKey: ['users'],
    queryFn: ({ signal }) => usersApi.list(signal),
    enabled,
  })
}

export function useUpdateUser(): Mutation<User, { id: Uuid; payload: UserUpdate }> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, payload }: { id: Uuid; payload: UserUpdate }) =>
      usersApi.update(id, payload),
    onSuccess: () => void client.invalidateQueries({ queryKey: ['users'] }),
  })
}

// ─── Créneaux de rendez-vous ───

/**
 * Mise à jour optimiste des grilles de créneaux.
 *
 * La grille se manipule au clic et au glisser : attendre l'aller-retour vers
 * Supabase — une seconde environ depuis Madagascar — rendait chaque geste
 * poussif. On applique donc l'effet immédiatement, on laisse l'appel partir en
 * fond, et on remet l'état d'avant si le serveur refuse.
 */
type SlotListSnapshot = [QueryKey, Slot[] | undefined][]

/** Un créneau posé localement, pas encore confirmé par le serveur. */
const OPTIMISTIC_PREFIX = 'optimistic:'

export function isOptimisticSlot(slot: Slot): boolean {
  return slot.id.startsWith(OPTIMISTIC_PREFIX)
}

function patchSlotLists(
  client: QueryClient,
  patch: (slots: Slot[]) => Slot[],
): SlotListSnapshot {
  const snapshot = client.getQueriesData<Slot[]>({ queryKey: ['slots', 'list'] })
  for (const [key, data] of snapshot) {
    if (data) client.setQueryData<Slot[]>(key, patch(data))
  }
  return snapshot
}

function restoreSlotLists(client: QueryClient, snapshot: SlotListSnapshot | undefined): void {
  if (!snapshot) return
  for (const [key, data] of snapshot) client.setQueryData(key, data)
}

/** Prépare une mutation optimiste : fige les requêtes en vol et photographie le cache. */
async function beginOptimistic(
  client: QueryClient,
  patch: (slots: Slot[]) => Slot[],
): Promise<SlotListSnapshot> {
  // Sans cette annulation, une requête déjà partie peut atterrir après notre
  // retouche et réinstaller l'état d'avant.
  await client.cancelQueries({ queryKey: queryKeys.slots.all })
  return patchSlotLists(client, patch)
}


export function useSlots(params: SlotWindowParams, enabled = true): Query<Slot[]> {
  return useQuery({
    queryKey: queryKeys.slots.list(params),
    queryFn: ({ signal }) => slotsApi.list(params, signal),
    enabled,
    // La grille doit refléter l'état réel : un créneau pris par quelqu'un
    // d'autre pendant qu'on hésite ne doit pas rester affiché comme libre.
    // Le hub temps réel invalide déjà à chaque changement ; ce délai court
    // couvre le cas d'une WebSocket coupée.
    staleTime: 5_000,
    refetchOnWindowFocus: true,
    placeholderData: (previous) => previous,
  })
}

export function useSlotOwners(): Query<SlotOwner[]> {
  return useQuery({
    queryKey: queryKeys.slots.owners,
    queryFn: ({ signal }) => slotsApi.owners(signal),
    staleTime: 5 * 60_000,
  })
}

export function useSlotRequests(
  params: { status?: SlotStatus | null; upcoming_only?: boolean } = {},
): Query<SlotRequest[]> {
  return useQuery({
    queryKey: queryKeys.slots.requests(params),
    queryFn: ({ signal }) => slotsApi.requests(params, signal),
    staleTime: 5_000,
  })
}

export interface OpenSlotsVars extends SlotOpenPayload {
  /** Propriétaire, pour peupler l'affichage avant la réponse du serveur. */
  owner: { id: Uuid; display_name: string }
}

export function useOpenSlots(): Mutation<SlotOpenResult, OpenSlotsVars> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ owner: _owner, ...payload }: OpenSlotsVars) => slotsApi.open(payload),
    onMutate: ({ starts_at, owner }) =>
      beginOptimistic(client, (slots) => {
        const existants = new Set(slots.map((slot) => slot.starts_at))
        const nouveaux: Slot[] = starts_at
          .filter((moment) => !existants.has(moment))
          .map((moment) => ({
            id: `${OPTIMISTIC_PREFIX}${moment}`,
            owner_user_id: owner.id,
            owner_display_name: owner.display_name,
            starts_at: moment,
            ends_at: new Date(new Date(moment).getTime() + 15 * 60_000).toISOString(),
            duration_minutes: 15,
            status: 'open',
            request_group_id: null,
            requested_by_user_id: null,
            requested_by_display_name: null,
            subject: null,
            is_mine: false,
            requested_at: null,
            decided_at: null,
          }))
        return [...slots, ...nouveaux]
      }),
    onError: (_error, _vars, snapshot) => restoreSlotLists(client, snapshot),
    onSettled: () => void client.invalidateQueries({ queryKey: queryKeys.slots.all }),
  })
}

export function useDeleteSlot(): Mutation<void, Uuid> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (slotId: Uuid) => slotsApi.remove(slotId),
    onMutate: (slotId) =>
      beginOptimistic(client, (slots) => slots.filter((slot) => slot.id !== slotId)),
    onError: (_error, _vars, snapshot) => restoreSlotLists(client, snapshot),
    onSettled: () => void client.invalidateQueries({ queryKey: queryKeys.slots.all }),
  })
}

export interface RequestSlotsVars extends SlotRequestPayload {
  /** Demandeur, pour afficher le rendez-vous avant la réponse du serveur. */
  requester: { id: Uuid; display_name: string }
}

export function useRequestSlots(): Mutation<SlotRequest, RequestSlotsVars> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ requester: _requester, ...payload }: RequestSlotsVars) =>
      slotsApi.requestSlots(payload),
    onMutate: ({ slot_ids, subject, requester }) => {
      const ids = new Set(slot_ids)
      const groupId = `${OPTIMISTIC_PREFIX}${crypto.randomUUID()}`
      return beginOptimistic(client, (slots) =>
        slots.map((slot) =>
          ids.has(slot.id)
            ? {
                ...slot,
                status: 'confirmed' as const,
                request_group_id: groupId,
                requested_by_user_id: requester.id,
                requested_by_display_name: requester.display_name,
                subject: subject ?? null,
                is_mine: true,
              }
            : slot,
        ),
      )
    },
    onError: (_error, _vars, snapshot) => restoreSlotLists(client, snapshot),
    onSettled: () => void client.invalidateQueries({ queryKey: queryKeys.slots.all }),
  })
}

export function useMoveSlots(): Mutation<Slot[], SlotMovePayload> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: SlotMovePayload) => slotsApi.move(payload),
    onMutate: ({ slot_ids, starts_at }) => {
      const ids = new Set(slot_ids)
      return beginOptimistic(client, (slots) => {
        const concernes = slots
          .filter((slot) => ids.has(slot.id))
          .sort((a, b) => a.starts_at.localeCompare(b.starts_at))
        const premier = concernes[0]
        if (!premier) return slots
        // Le décalage se lit sur le premier créneau, comme côté serveur :
        // aligner chaque ligne sur la cible les empilerait au même horaire.
        const delta = new Date(starts_at).getTime() - new Date(premier.starts_at).getTime()
        return slots.map((slot) => {
          if (!ids.has(slot.id)) return slot
          return {
            ...slot,
            starts_at: new Date(new Date(slot.starts_at).getTime() + delta).toISOString(),
            ends_at: new Date(new Date(slot.ends_at).getTime() + delta).toISOString(),
          }
        })
      })
    },
    onError: (_error, _vars, snapshot) => restoreSlotLists(client, snapshot),
    onSettled: () => void client.invalidateQueries({ queryKey: queryKeys.slots.all }),
  })
}

export function useCancelSlotRequest(): Mutation<void, Uuid> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (groupId: Uuid) => slotsApi.cancel(groupId),
    onMutate: (groupId) =>
      beginOptimistic(client, (slots) =>
        slots.map((slot) =>
          slot.request_group_id === groupId
            ? {
                ...slot,
                status: 'open' as const,
                request_group_id: null,
                requested_by_user_id: null,
                requested_by_display_name: null,
                subject: null,
                is_mine: false,
              }
            : slot,
        ),
      ),
    onError: (_error, _vars, snapshot) => restoreSlotLists(client, snapshot),
    onSettled: () => void client.invalidateQueries({ queryKey: queryKeys.slots.all }),
  })
}

// ─── Rapports de fin de journée ───

export function useTodayReport(day?: string): Query<TodayReport> {
  return useQuery({
    queryKey: queryKeys.dailyReports.today(day),
    queryFn: ({ signal }) => dailyReportsApi.today(day, signal),
    // Le bandeau de rappel s'appuie sur `has_content` : le laisser vieillir
    // ferait réapparaître le rappel à quelqu'un qui vient de saisir.
    staleTime: 15_000,
  })
}

export function useSaveDailyReport(): Mutation<
  DailyReport,
  { day: string; payload: DailyReportPayload }
> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ day, payload }: { day: string; payload: DailyReportPayload }) =>
      dailyReportsApi.save(day, payload),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.dailyReports.all })
      // Cocher « terminée » porte l'action à 100 % : compteurs et rapports
      // consolidés changent avec elle.
      void client.invalidateQueries({ queryKey: queryKeys.actions.all })
      void client.invalidateQueries({ queryKey: queryKeys.reports.all })
    },
  })
}

export function useSubmitDailyReport(): Mutation<DailyReport, string> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (day: string) => dailyReportsApi.submit(day),
    onSuccess: () => void client.invalidateQueries({ queryKey: queryKeys.dailyReports.all }),
  })
}

export function useDailyReportHistory(params: {
  from: string
  to: string
  user_id?: string | null
}): Query<DailyReport[]> {
  return useQuery({
    queryKey: queryKeys.dailyReports.history(params),
    queryFn: ({ signal }) => dailyReportsApi.history(params, signal),
  })
}
