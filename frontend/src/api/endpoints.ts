/**
 * Fonctions d'appel, une par route de l'API.
 *
 * Elles ne contiennent aucune logique de cache : c'est le rôle des hooks
 * TanStack Query de `api/queries.ts`. Les garder séparées permet de les
 * appeler aussi hors React (préchargement du routeur, exports).
 */

import { request, requestPage, requestVoid, type QueryParams } from './client'
import type {
  Action,
  ActionCreate,
  ActionSummary,
  ActionUpdate,
  ActionView,
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
  RelancePreview,
  RelanceSendResult,
  Responsable,
  ResponsableCreate,
  ResponsableUpdate,
  SyncLog,
  User,
  UserUpdate,
  Uuid,
  ActionStatus,
  WorkloadReport,
  Slot,
  SlotOpenPayload,
  SlotOpenResult,
  SlotOwner,
  SlotRequest,
  SlotRequestPayload,
  SlotMovePayload,
  SlotStatus,
  CurrentUser,
} from './types'

// ─── Authentification ───

export const auth = {
  me: (signal?: AbortSignal) => request<CurrentUser>('/auth/me', { signal }),
}

// ─── Projets ───

export interface ProjectListParams {
  is_active?: boolean | null
  limit?: number
  offset?: number
}

export const projects = {
  list: (params: ProjectListParams = {}, signal?: AbortSignal): Promise<Page<Project>> =>
    requestPage<Project>('/projects', { query: params as QueryParams, signal }),

  get: (id: Uuid, signal?: AbortSignal) =>
    request<ProjectWithActions>(`/projects/${id}`, { signal }),

  create: (payload: ProjectCreate) =>
    request<Project>('/projects', { method: 'POST', body: payload }),

  update: (id: Uuid, payload: ProjectUpdate) =>
    request<Project>(`/projects/${id}`, { method: 'PUT', body: payload }),

  remove: (id: Uuid) => requestVoid(`/projects/${id}`, { method: 'DELETE' }),
}

// ─── Actions ───

export interface ActionListParams {
  view?: ActionView
  project_id?: Uuid | null
  responsable_id?: Uuid | null
  responsable?: string | null
  status?: ActionStatus | null
  search?: string | null
  active_projects_only?: boolean
  due_soon_days?: number
  weeks_ahead?: number
  limit?: number
  offset?: number
}

export const actions = {
  list: (params: ActionListParams = {}, signal?: AbortSignal): Promise<Page<Action>> =>
    requestPage<Action>('/actions', { query: params as QueryParams, signal }),

  summary: (signal?: AbortSignal) => request<ActionSummary>('/actions/summary', { signal }),

  get: (id: Uuid, signal?: AbortSignal) => request<Action>(`/actions/${id}`, { signal }),

  create: (payload: ActionCreate) => request<Action>('/actions', { method: 'POST', body: payload }),

  update: (id: Uuid, payload: ActionUpdate) =>
    request<Action>(`/actions/${id}`, { method: 'PUT', body: payload }),

  remove: (id: Uuid) => requestVoid(`/actions/${id}`, { method: 'DELETE' }),
}

// ─── Responsables ───

export interface ResponsableListParams {
  unmapped_only?: boolean
  limit?: number
  offset?: number
}

export const responsables = {
  list: (params: ResponsableListParams = {}, signal?: AbortSignal): Promise<Page<Responsable>> =>
    requestPage<Responsable>('/responsables', { query: params as QueryParams, signal }),

  get: (id: Uuid, signal?: AbortSignal) => request<Responsable>(`/responsables/${id}`, { signal }),

  create: (payload: ResponsableCreate) =>
    request<Responsable>('/responsables', { method: 'POST', body: payload }),

  update: (id: Uuid, payload: ResponsableUpdate) =>
    request<Responsable>(`/responsables/${id}`, { method: 'PUT', body: payload }),

  remove: (id: Uuid) => requestVoid(`/responsables/${id}`, { method: 'DELETE' }),
}

// ─── Rapports ───

export const reports = {
  portfolio: (scope: 'active' | 'all' = 'active', signal?: AbortSignal) =>
    request<PortfolioReport>('/reports/portfolio', { query: { scope }, signal }),

  project: (id: Uuid, signal?: AbortSignal) =>
    request<ProjectReport>(`/reports/projects/${id}`, { signal }),

  workload: (activeProjectsOnly = true, signal?: AbortSignal) =>
    request<WorkloadReport>('/reports/workload', {
      query: { active_projects_only: activeProjectsOnly },
      signal,
    }),

  forecast: (
    params: { weeks?: number; start_offset?: number; include_actions?: boolean; active_projects_only?: boolean } = {},
    signal?: AbortSignal,
  ) => request<ForecastReport>('/reports/forecast', { query: params, signal }),
}

// ─── Relances ───

export const relances = {
  config: (signal?: AbortSignal) => request<RelanceConfig>('/relances/config', { signal }),

  preview: (responsableId: Uuid, kind: RelanceKind, signal?: AbortSignal) =>
    request<RelancePreview>(`/relances/${responsableId}/preview`, { query: { kind }, signal }),

  send: (responsableId: Uuid, kind: RelanceKind) =>
    request<RelanceSendResult>(`/relances/${responsableId}/send`, {
      method: 'POST',
      query: { kind },
    }),

  sendBatch: (kind: RelanceKind) =>
    request<RelanceBatch>('/relances/send', { method: 'POST', query: { kind } }),
}

// ─── Journaux ───

export const logs = {
  sync: (limit = 50, signal?: AbortSignal): Promise<Page<SyncLog>> =>
    requestPage<SyncLog>('/sync-logs', { query: { limit }, signal }),

  relances: (limit = 50, signal?: AbortSignal): Promise<Page<RelanceLog>> =>
    requestPage<RelanceLog>('/relance-logs', { query: { limit }, signal }),
}

// ─── Utilisateurs (admin) ───

export const users = {
  list: (signal?: AbortSignal): Promise<Page<User>> => requestPage<User>('/users', { signal }),

  get: (id: Uuid, signal?: AbortSignal) => request<User>(`/users/${id}`, { signal }),

  update: (id: Uuid, payload: UserUpdate) =>
    request<User>(`/users/${id}`, { method: 'PUT', body: payload }),

  remove: (id: Uuid) => requestVoid(`/users/${id}`, { method: 'DELETE' }),
}

// ─── Créneaux de rendez-vous ───

export interface SlotWindowParams extends QueryParams {
  /** Bornes de la fenêtre, horodatées avec leur fuseau. */
  from: string
  to: string
  /** Omis, la fenêtre couvre tous les propriétaires — un appel de moins. */
  owner_id?: Uuid | null
  mine_only?: boolean
}

export const slots = {
  list: (params: SlotWindowParams, signal?: AbortSignal) =>
    request<Slot[]>('/slots', { query: params, signal }),

  owners: (signal?: AbortSignal) => request<SlotOwner[]>('/slots/owners', { signal }),

  requests: (
    params: { status?: SlotStatus | null; upcoming_only?: boolean } = {},
    signal?: AbortSignal,
  ) => request<SlotRequest[]>('/slots/requests', { query: params, signal }),

  open: (payload: SlotOpenPayload) =>
    request<SlotOpenResult>('/slots', { method: 'POST', body: payload }),

  remove: (slotId: Uuid) => requestVoid(`/slots/${slotId}`, { method: 'DELETE' }),

  requestSlots: (payload: SlotRequestPayload) =>
    request<SlotRequest>('/slots/requests', { method: 'POST', body: payload }),

  move: (payload: SlotMovePayload) =>
    request<Slot[]>('/slots/move', { method: 'POST', body: payload }),

  cancel: (groupId: Uuid) => requestVoid(`/slots/requests/${groupId}`, { method: 'DELETE' }),
}

export const api = {
  auth,
  slots,
  projects,
  actions,
  responsables,
  reports,
  relances,
  logs,
  users,
}
