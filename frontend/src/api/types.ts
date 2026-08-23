/**
 * Types du domaine — miroir des schémas Pydantic exposés par core-api,
 * auth-api et le hub temps réel.
 *
 * Les identifiants restent des `string` (UUID sérialisés en JSON) et les
 * dates des chaînes ISO : la conversion se fait au bord, dans les
 * composants, via `lib/date`.
 */

export type Uuid = string
/** `YYYY-MM-DD` */
export type IsoDate = string
/** `YYYY-MM-DDTHH:MM:SS±HH:MM` */
export type IsoDateTime = string

// ─── Énumérations ───

export const ACTION_STATUSES = ['a_faire', 'en_cours', 'en_retard', 'bloque', 'termine'] as const
export type ActionStatus = (typeof ACTION_STATUSES)[number]

/** Statuts qu'un client a le droit d'imposer (les autres sont déduits). */
export const ASSIGNABLE_ACTION_STATUSES = ['a_faire', 'en_cours', 'bloque'] as const
export type AssignableActionStatus = (typeof ASSIGNABLE_ACTION_STATUSES)[number]

export const ACTION_VIEWS = [
  'all',
  'open',
  'overdue',
  'today',
  'due_soon',
  'upcoming',
  'in_progress',
  'blocked',
  'done',
  'unassigned',
  'no_deadline',
] as const
export type ActionView = (typeof ACTION_VIEWS)[number]

export type SyncStatus = 'running' | 'success' | 'failed'
export type UserRole = 'admin' | 'responsable_si' | 'lecteur' | 'dsio'
export type ProjectHealth = 'ok' | 'attention' | 'critique'
export type RelanceKind = 'overdue' | 'today' | 'due_soon'

export const ACTION_STATUS_LABELS: Record<ActionStatus, string> = {
  a_faire: 'À faire',
  en_cours: 'En cours',
  en_retard: 'En retard',
  bloque: 'Bloquée',
  termine: 'Terminée',
}

export const ACTION_VIEW_LABELS: Record<ActionView, string> = {
  all: 'Toutes',
  open: 'Ouvertes',
  overdue: 'En retard',
  today: "Aujourd'hui",
  due_soon: 'Échéance proche',
  upcoming: 'À venir',
  in_progress: 'En cours',
  blocked: 'Bloquées',
  done: 'Terminées',
  unassigned: 'Non assignées',
  no_deadline: 'Sans échéance',
}

export const USER_ROLE_LABELS: Record<UserRole, string> = {
  admin: 'Administrateur',
  responsable_si: 'Responsable SI',
  lecteur: 'Lecteur',
  dsio: 'DSIO',
}

// ─── Responsables ───

export interface Responsable {
  id: Uuid
  display_name: string
  email: string | null
  is_mapped: boolean
}

export interface ResponsableCreate {
  display_name: string
  email?: string | null
}

export interface ResponsableUpdate {
  display_name?: string
  email?: string | null
}

// ─── Actions ───

export interface Action {
  id: Uuid
  numero: string
  phase: string | null
  project_id: Uuid
  description: string
  resp_suivi: string | null
  status: ActionStatus
  progress: number
  deadline: IsoDate | null
  date_realisation: IsoDate | null
  charges_hj: number | null
  commentaire: string | null
  /** Calculé côté serveur : suit l'avancement. */
  spi: number
  /** Calculé côté serveur : 100 si livrée à temps, 0 sinon. */
  otd: number
  responsables: Responsable[]
  created_at: IsoDateTime
  updated_at: IsoDateTime
}

export interface ActionCreate {
  description: string
  resp_suivi: string
  deadline: IsoDate
  project_id: Uuid
  responsable_names: string[]
  phase?: string | null
  progress?: number
  date_realisation?: IsoDate | null
  charges_hj?: number | null
  commentaire?: string | null
}

export interface ActionUpdate {
  description?: string
  resp_suivi?: string
  progress?: number
  deadline?: IsoDate | null
  date_realisation?: IsoDate | null
  charges_hj?: number
  commentaire?: string | null
  status?: AssignableActionStatus
  phase?: string | null
  responsable_names?: string[]
}

// ─── Projets ───

export interface Project {
  id: Uuid
  code: string
  name: string
  source_file_path: string
  has_phases: boolean
  is_active: boolean
  created_at: IsoDateTime
  last_synced_at: IsoDateTime | null
}

export interface ProjectWithActions extends Project {
  actions: Action[]
}

export interface ProjectCreate {
  code: string
  name: string
  source_file_path: string
  has_phases?: boolean
}

export interface ProjectUpdate {
  name?: string
  source_file_path?: string
  is_active?: boolean
  has_phases?: boolean
}

// ─── Journaux ───

export interface SyncLog {
  id: Uuid
  started_at: IsoDateTime
  finished_at: IsoDateTime | null
  status: SyncStatus
  files_processed: number
  error_message: string | null
}

export interface RelanceLog {
  id: Uuid
  responsable_id: Uuid
  sent_at: IsoDateTime
  email_status: string
}

// ─── Rapports ───

export interface ActionSummary {
  generated_at: IsoDateTime
  /** Clés = valeurs de `ActionView`. */
  counts: Partial<Record<ActionView, number>> & Record<string, number>
  overdue_ratio: number
}

export interface ActionDigest {
  id: Uuid
  numero: string
  description: string
  project_code: string | null
  project_name: string | null
  status: ActionStatus
  progress: number
  deadline: IsoDate | null
  days_left: number | null
  resp_suivi: string | null
  responsables: string[]
}

export interface ProjectReport {
  project_id: Uuid
  code: string
  name: string
  is_active: boolean
  last_synced_at: IsoDateTime | null
  total_actions: number
  done: number
  open: number
  overdue: number
  blocked: number
  due_soon: number
  unassigned: number
  no_deadline: number
  progress_avg: number
  completion_rate: number
  overdue_rate: number
  spi_avg: number
  otd_avg: number
  charges_hj_total: number
  health: ProjectHealth
}

export interface PortfolioReport {
  generated_at: IsoDateTime
  scope: 'active' | 'all'
  project_count: number
  totals: ActionSummary
  projects: ProjectReport[]
}

export interface ResponsableReport {
  responsable_id: Uuid
  display_name: string
  email: string | null
  is_mapped: boolean
  total_actions: number
  open: number
  overdue: number
  due_soon: number
  blocked: number
  done: number
  progress_avg: number
  overdue_rate: number
  next_deadline: IsoDate | null
  last_relance_at: IsoDateTime | null
}

export interface WorkloadReport {
  generated_at: IsoDateTime
  responsable_count: number
  unassigned_actions: number
  responsables: ResponsableReport[]
}

export interface WeekBucket {
  week_start: IsoDate
  week_end: IsoDate
  label: string
  action_count: number
  charges_hj: number
  actions: ActionDigest[]
}

export interface ForecastReport {
  generated_at: IsoDateTime
  weeks: WeekBucket[]
  overdue_backlog: number
}

// ─── Relances ───

export interface RelanceConfig {
  mode: 'graph' | 'dry_run'
  explanation: string
  sender: string | null
  cooldown_days: number
  horizon_days: number
}

export interface RelancePreview {
  responsable_id: Uuid
  responsable_name: string
  email: string | null
  is_mapped: boolean
  kind: RelanceKind
  subject: string
  action_count: number
  actions: ActionDigest[]
  html: string
  text: string
  would_send: boolean
  skip_reason: string | null
}

export interface RelanceSendResult {
  responsable_id: Uuid
  responsable_name: string
  email: string | null
  kind: RelanceKind
  status: 'sent' | 'simulated' | 'failed' | 'skipped_no_email' | 'skipped'
  action_count: number
  detail: string | null
  relance_log_id: Uuid | null
}

export interface RelanceBatch {
  generated_at: IsoDateTime
  kind: RelanceKind
  mode: string
  considered: number
  sent: number
  simulated: number
  failed: number
  skipped: number
  results: RelanceSendResult[]
}

// ─── Utilisateurs ───

export interface User {
  id: Uuid
  email: string
  display_name: string
  role: UserRole
  is_active: boolean
  created_at: IsoDateTime
  last_login_at: IsoDateTime | null
}

/** Fiche responsable rattachée à un compte, via l'email. */
export interface LinkedResponsable {
  id: Uuid
  display_name: string
}

/** Profil de l'appelant, enrichi de son périmètre de lecture. */
export interface CurrentUser extends User {
  /** Vrai pour `admin` et `dsio` : vue complète du portefeuille. */
  sees_all_data: boolean
  /**
   * Fiches responsable portant l'email du compte. Vide sur un compte
   * cloisonné, il ne voit rien tant qu'un administrateur ne l'associe pas.
   */
  linked_responsables: LinkedResponsable[]
}

export interface UserUpdate {
  role?: UserRole
  is_active?: boolean
}

// ─── Temps réel ───

export type RealtimeEventType =
  | 'project_created'
  | 'project_updated'
  | 'project_deleted'
  | 'action_created'
  | 'action_updated'
  | 'action_deleted'
  | 'responsable_created'
  | 'responsable_updated'
  | 'responsable_deleted'
  | 'slot_created'
  | 'slot_deleted'
  | 'slot_confirmed'
  | 'slot_released'
  | 'slot_moved'
  | 'ping'

export interface RealtimeEvent {
  type: RealtimeEventType
  payload?: Record<string, unknown>
}

// ─── Créneaux de rendez-vous ───

export const SLOT_STATUSES = ['open', 'confirmed'] as const
export type SlotStatus = (typeof SLOT_STATUSES)[number]

export const SLOT_STATUS_LABELS: Record<SlotStatus, string> = {
  open: 'Disponible',
  confirmed: 'Réservé',
}

/** Un quart d'heure. Une plage d'une heure est quatre créneaux consécutifs. */
export interface Slot {
  id: Uuid
  owner_user_id: Uuid
  owner_display_name: string
  starts_at: IsoDateTime
  ends_at: IsoDateTime
  duration_minutes: number
  status: SlotStatus
  request_group_id: Uuid | null
  /** Absent pour un tiers : seul le DSIO, un admin ou le demandeur le voient. */
  requested_by_user_id: Uuid | null
  requested_by_display_name: string | null
  subject: string | null
  is_mine: boolean
  requested_at: IsoDateTime | null
  decided_at: IsoDateTime | null
}

/** Un rendez-vous : les quarts d'heure d'un même `request_group_id`. */
export interface SlotRequest {
  request_group_id: Uuid
  owner_user_id: Uuid
  owner_display_name: string
  requested_by_user_id: Uuid | null
  requested_by_display_name: string | null
  subject: string | null
  status: SlotStatus
  starts_at: IsoDateTime
  ends_at: IsoDateTime
  slot_count: number
  duration_minutes: number
  requested_at: IsoDateTime | null
  decided_at: IsoDateTime | null
  is_mine: boolean
}

export interface SlotOwner {
  id: Uuid
  display_name: string
  email: string
}

export interface SlotOpenPayload {
  starts_at: IsoDateTime[]
}

export interface SlotOpenResult {
  created: number
  skipped: number
  slots: Slot[]
}

export interface SlotRequestPayload {
  slot_ids: Uuid[]
  subject?: string | null
}

export interface SlotMovePayload {
  slot_ids: Uuid[]
  /** Nouvel horaire du premier créneau ; le décalage s'applique aux autres. */
  starts_at: IsoDateTime
}

// ─── Pagination ───

/** Résultat d'une liste paginée : `total` vient de l'en-tête `X-Total-Count`. */
export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}
