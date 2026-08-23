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
  actions as actionsApi,
  logs as logsApi,
  projects as projectsApi,
  relances as relancesApi,
  reports as reportsApi,
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
  RelanceBatch,
  RelanceConfig,
  RelanceKind,
  RelanceLog,
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
} from './types'

type Query<T> = UseQueryResult<T, ApiError>
type Mutation<TData, TVars> = UseMutationResult<TData, ApiError, TVars>

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

export function useUpdateProject(): Mutation<Project, { id: Uuid; payload: ProjectUpdate }> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, payload }: { id: Uuid; payload: ProjectUpdate }) =>
      projectsApi.update(id, payload),
    onSuccess: () => {
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

export function useUpdateAction(): Mutation<Action, { id: Uuid; payload: ActionUpdate }> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, payload }: { id: Uuid; payload: ActionUpdate }) =>
      actionsApi.update(id, payload),
    onSuccess: () => {
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

export function useRelanceConfig(): Query<RelanceConfig> {
  return useQuery({
    queryKey: queryKeys.relances.config,
    queryFn: ({ signal }) => relancesApi.config(signal),
    // La configuration d'envoi ne change qu'au redémarrage d'un conteneur.
    staleTime: 5 * 60_000,
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
