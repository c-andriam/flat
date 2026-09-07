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
  ActionSort,
  ActionSummary,
  ActionUpdate,
  ActionView,
  ChampsGabarit,
  ForecastReport,
  Gabarit,
  GabaritCreate,
  GabaritEntite,
  GabaritUpdate,
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
  RelancePreview,
  RelanceSendResult,
  Responsable,
  ResponsableCreate,
  ResponsableUpdate,
  SortOrder,
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
  DailyReport,
  DailyReportPayload,
  TodayReport,
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
  /** Colonne de tri ; omise, l'API renvoie les actions par urgence. */
  sort?: ActionSort | null
  order?: SortOrder
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

  // ─── Récapitulatif planifié ───

  /** Réglages du compte connecté. Accessible même en lecture seule. */
  myPreference: (signal?: AbortSignal) =>
    request<RelancePreference>('/relances/preferences/me', { signal }),

  updateMyPreference: (payload: RelancePreferenceUpdate) =>
    request<RelancePreference>('/relances/preferences/me', {
      method: 'PUT',
      body: payload,
    }),

  /** Réglages de toute l'équipe — réservé aux administrateurs. */
  preferences: (tous = false, signal?: AbortSignal) =>
    request<RelancePreference[]>('/relances/preferences', { query: { tous }, signal }),

  updatePreference: (responsableId: Uuid, payload: RelancePreferenceUpdate) =>
    request<RelancePreference>(`/relances/preferences/${responsableId}`, {
      method: 'PUT',
      body: payload,
    }),

  digest: (responsableId: Uuid, signal?: AbortSignal) =>
    request<RelanceDigestPreview>(`/relances/${responsableId}/digest`, { signal }),

  sendDigest: (responsableId: Uuid) =>
    request<RelanceDigestSendResult>(`/relances/${responsableId}/digest/send`, {
      method: 'POST',
    }),

  sendDigestBatch: (dryRun = false) =>
    request<RelanceDigestBatch>('/relances/digests/send', {
      method: 'POST',
      query: { dry_run: dryRun },
    }),
}

// ─── Paramétrage : référentiels ───

export const referentiels = {
  /**
   * Toutes les listes en un appel. Les formulaires en ont besoin de plusieurs
   * à la fois, et quatre allers-retours sur une base distante coûtent plus
   * que la réponse elle-même.
   */
  list: (inclureInactifs = false, signal?: AbortSignal) =>
    request<ReferentielListe[]>('/referentiels', {
      query: { inclure_inactifs: inclureInactifs },
      signal,
    }),

  create: (payload: ReferentielCreate) =>
    request<Referentiel>('/referentiels', { method: 'POST', body: payload }),

  update: (id: Uuid, payload: ReferentielUpdate) =>
    request<Referentiel>(`/referentiels/${id}`, { method: 'PUT', body: payload }),

  remove: (id: Uuid) => requestVoid(`/referentiels/${id}`, { method: 'DELETE' }),
}

// ─── Paramétrage : gabarits ───

export const gabarits = {
  list: (
    params: { entite?: GabaritEntite | null; inclure_inactifs?: boolean } = {},
    signal?: AbortSignal,
  ) => request<Gabarit[]>('/gabarits', { query: params as QueryParams, signal }),

  /** Champs préremplissables, lus sur les schémas de création côté serveur. */
  champs: (signal?: AbortSignal) =>
    request<ChampsGabarit[]>('/gabarits/champs', { signal }),

  create: (payload: GabaritCreate) =>
    request<Gabarit>('/gabarits', { method: 'POST', body: payload }),

  update: (id: Uuid, payload: GabaritUpdate) =>
    request<Gabarit>(`/gabarits/${id}`, { method: 'PUT', body: payload }),

  remove: (id: Uuid) => requestVoid(`/gabarits/${id}`, { method: 'DELETE' }),

  /**
   * Crée un projet depuis un gabarit. Tous les champs sont facultatifs : ce
   * que le gabarit fournit n'a pas à être répété.
   */
  creerProjet: (gabaritId: Uuid, payload: Partial<ProjectCreate>) =>
    request<ProjectWithActions>(`/projects/depuis-gabarit/${gabaritId}`, {
      method: 'POST',
      body: payload,
    }),

  creerAction: (gabaritId: Uuid, payload: Partial<ActionCreate>) =>
    request<Action>(`/actions/depuis-gabarit/${gabaritId}`, {
      method: 'POST',
      body: payload,
    }),
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

// ─── Rapports de fin de journée ───

export const dailyReports = {
  today: (day: string | undefined, signal?: AbortSignal) =>
    request<TodayReport>('/daily-reports/today', { query: day ? { day } : {}, signal }),

  save: (day: string, payload: DailyReportPayload) =>
    request<DailyReport>(`/daily-reports/${day}`, { method: 'PUT', body: payload }),

  submit: (day: string) =>
    request<DailyReport>(`/daily-reports/${day}/submit`, { method: 'POST' }),

  remove: (day: string) => requestVoid(`/daily-reports/${day}`, { method: 'DELETE' }),

  history: (params: { from: string; to: string; user_id?: Uuid | null }, signal?: AbortSignal) =>
    request<DailyReport[]>('/daily-reports', { query: params, signal }),
}

export const api = {
  auth,
  referentiels,
  gabarits,
  slots,
  dailyReports,
  projects,
  actions,
  responsables,
  reports,
  relances,
  logs,
  users,
}
