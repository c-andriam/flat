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

/**
 * Colonnes sur lesquelles l'API accepte de trier.
 *
 * Le tri porte sur l'ensemble du résultat, pas sur la page affichée : sans
 * lui, les actions d'un projet donné se retrouvent dispersées sur plusieurs
 * pages, l'ordre par défaut étant l'urgence.
 */
export const ACTION_SORTS = ['deadline', 'project', 'numero', 'progress', 'status'] as const
export type ActionSort = (typeof ACTION_SORTS)[number]
export type SortOrder = 'asc' | 'desc'

export function isActionSort(value: string | null): value is ActionSort {
  return value !== null && (ACTION_SORTS as readonly string[]).includes(value)
}

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
  /**
   * Code et nom du projet porteur, repris par les routes de liste pour éviter
   * un appel par projet. `null` sur les routes qui ne chargent pas la
   * relation — le détail d'un projet, où celui-ci est déjà connu.
   */
  project_code: string | null
  project_name: string | null
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
  /**
   * Responsables de suivi résolus en fiches — ce sont eux qui reçoivent le
   * récapitulatif de relance. `resp_suivi` reste la cellule brute du classeur ;
   * cette liste en est la lecture exploitable, découpée quand la cellule nomme
   * plusieurs personnes.
   */
  suiveurs: Responsable[]
  /** En veille : l'action reste au tableau de bord mais sort des relances. */
  is_standby: boolean
  standby_reason: string | null
  /** Catégorie, prise dans le référentiel `categorie_action`. */
  categorie_id: Uuid | null
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
  categorie_id?: Uuid | null
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
  is_standby?: boolean
  standby_reason?: string | null
  categorie_id?: Uuid | null
}

// ─── Projets ───

export interface Project {
  id: Uuid
  code: string
  name: string
  source_file_path: string
  has_phases: boolean
  is_active: boolean
  /**
   * En veille : le projet reste visible et compté, mais aucune de ses actions
   * ne déclenche de relance. Distinct de `is_active: false`, qui le fait
   * disparaître des tableaux de bord.
   */
  is_standby: boolean
  standby_reason: string | null
  /** Nature du projet, prise dans le référentiel `type_projet`. */
  type_id: Uuid | null
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
  type_id?: Uuid | null
}

export interface ProjectUpdate {
  name?: string
  source_file_path?: string
  is_active?: boolean
  has_phases?: boolean
  is_standby?: boolean
  standby_reason?: string | null
  type_id?: Uuid | null
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
  /** `digest` pour un récapitulatif planifié, sinon la nature du rappel. */
  kind: string
  action_count: number
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

// ─── Récapitulatif planifié ───

/** Quelles actions figurent dans le récapitulatif d'une personne. */
export type RelancePerimetre = 'suivi' | 'realisation' | 'les_deux'

export const RELANCE_PERIMETRE_LABELS: Record<RelancePerimetre, string> = {
  suivi: 'Actions que je suis',
  realisation: 'Actions que je réalise',
  les_deux: 'Les deux',
}

/** Sections du récapitulatif, dans l'ordre d'apparition dans le message. */
export type RelanceSectionKey = 'overdue' | 'today' | 'due_soon' | 'pending'

export const RELANCE_SECTION_LABELS: Record<RelanceSectionKey, string> = {
  overdue: 'En retard',
  today: "À rendre aujourd'hui",
  due_soon: 'Échéances proches',
  pending: 'En attente',
}

/** Lundi = 0, comme `date.weekday()` côté Python. */
export const JOURS_SEMAINE = [
  { value: 0, court: 'L', label: 'lundi' },
  { value: 1, court: 'M', label: 'mardi' },
  { value: 2, court: 'M', label: 'mercredi' },
  { value: 3, court: 'J', label: 'jeudi' },
  { value: 4, court: 'V', label: 'vendredi' },
  { value: 5, court: 'S', label: 'samedi' },
  { value: 6, court: 'D', label: 'dimanche' },
] as const

export interface RelancePreference {
  responsable_id: Uuid
  responsable_name: string
  email: string | null
  is_mapped: boolean
  /** Faux tant que rien n'a été réglé : les valeurs sont celles par défaut. */
  personnalise: boolean
  enabled: boolean
  perimeter: RelancePerimetre
  /** Indices de jours ; leur nombre *est* la fréquence hebdomadaire. */
  days_of_week: number[]
  send_hour: number
  include_overdue: boolean
  include_today: boolean
  include_due_soon: boolean
  include_pending: boolean
  horizon_days: number
  frequence_hebdomadaire: number
  /** Cadence en clair, telle qu'elle figure en pied de message. */
  cadence: string
  jours_labels: string[]
}

export interface RelancePreferenceUpdate {
  enabled?: boolean
  perimeter?: RelancePerimetre
  days_of_week?: number[]
  send_hour?: number
  include_overdue?: boolean
  include_today?: boolean
  include_due_soon?: boolean
  include_pending?: boolean
  horizon_days?: number
}

export interface RelanceSection {
  key: RelanceSectionKey
  label: string
  intro: string
  action_count: number
  actions: ActionDigest[]
}

export interface RelanceDigestPreview {
  responsable_id: Uuid
  responsable_name: string
  email: string | null
  is_mapped: boolean
  preference: RelancePreference
  subject: string
  action_count: number
  sections: RelanceSection[]
  html: string
  text: string
  would_send: boolean
  skip_reason: string | null
  /** Prochain envoi automatique, `null` si les relances sont coupées. */
  next_send_at: IsoDateTime | null
}

export interface RelanceDigestSendResult {
  responsable_id: Uuid
  responsable_name: string
  email: string | null
  status: 'sent' | 'simulated' | 'failed' | 'skipped_no_email' | 'skipped'
  action_count: number
  detail: string | null
  relance_log_id: Uuid | null
}

export interface RelanceDigestBatch {
  generated_at: IsoDateTime
  mode: string
  considered: number
  sent: number
  simulated: number
  failed: number
  skipped: number
  results: RelanceDigestSendResult[]
}

// ─── Paramétrage : référentiels et gabarits ───

/**
 * Listes administrables reconnues par l'application.
 *
 * Fermée volontairement : ajouter une *valeur* est un acte d'administration,
 * ajouter un *type* est un développement, puisqu'il faut du code pour le
 * consommer. Des types libres produiraient des listes que rien ne lit.
 */
export type ReferentielType =
  | 'type_projet'
  | 'categorie_action'
  | 'salle'
  | 'type_reunion'

export interface Referentiel {
  id: Uuid
  type: ReferentielType
  /** Identifiant stable, insensible au renommage du libellé. */
  code: string
  label: string
  description: string | null
  /** Couleur du badge en hexadécimal, ou `null` pour la teinte neutre. */
  color: string | null
  position: number
  is_active: boolean
  parent_id: Uuid | null
  /** Propriétés propres à la valeur — `{ capacite: 12 }` pour une salle. */
  attributs: Record<string, unknown> | null
  created_at: IsoDateTime
  updated_at: IsoDateTime
}

/** Une liste administrable et ses valeurs. */
export interface ReferentielListe {
  type: ReferentielType
  label: string
  values: Referentiel[]
}

export interface ReferentielCreate {
  type: ReferentielType
  code: string
  label: string
  description?: string | null
  color?: string | null
  position?: number
  parent_id?: Uuid | null
  attributs?: Record<string, unknown> | null
}

/** Ni `type` ni `code` : les déplacer romprait les rattachements existants. */
export interface ReferentielUpdate {
  label?: string
  description?: string | null
  color?: string | null
  position?: number
  parent_id?: Uuid | null
  attributs?: Record<string, unknown> | null
  is_active?: boolean
}

export type GabaritEntite = 'projet' | 'action'

export const GABARIT_ENTITE_LABELS: Record<GabaritEntite, string> = {
  projet: 'Projet',
  action: 'Action',
}

/** Contraintes de saisie applicables à un champ. */
export interface RegleChamp {
  obligatoire?: boolean
  masque?: boolean
  verrouille?: boolean
}

export interface GabaritActionModele {
  id?: Uuid
  description: string
  position: number
  phase?: string | null
  resp_suivi?: string | null
  responsable_names: string[]
  /** Échéance en jours depuis la création : une date absolue serait périmée. */
  delai_jours?: number | null
  charges_hj?: number | null
  categorie_id?: Uuid | null
}

export interface Gabarit {
  id: Uuid
  entite: GabaritEntite
  nom: string
  description: string | null
  /** Valeurs préremplies, par nom de champ du schéma de création. */
  valeurs: Record<string, unknown>
  /** Contraintes de saisie, par champ. */
  politique: Record<string, RegleChamp>
  is_active: boolean
  is_default: boolean
  position: number
  actions: GabaritActionModele[]
  created_at: IsoDateTime
  updated_at: IsoDateTime
}

export interface GabaritCreate {
  entite: GabaritEntite
  nom: string
  description?: string | null
  valeurs?: Record<string, unknown>
  politique?: Record<string, RegleChamp>
  is_active?: boolean
  is_default?: boolean
  position?: number
  actions?: GabaritActionModele[]
}

/** `entite` est absent : en changer rendrait valeurs et politique invalides. */
export interface GabaritUpdate {
  nom?: string
  description?: string | null
  valeurs?: Record<string, unknown>
  politique?: Record<string, RegleChamp>
  is_active?: boolean
  is_default?: boolean
  position?: number
  actions?: GabaritActionModele[]
}

/**
 * Nature d'un champ, telle que l'interface doit la présenter.
 *
 * Déduite côté serveur des annotations du schéma de création : une table de
 * correspondance tenue ici se serait désynchronisée au premier champ ajouté,
 * et l'écran d'administration aurait proposé le mauvais contrôle.
 */
export type TypeChamp =
  | 'texte'
  | 'texte_long'
  | 'nombre'
  | 'booleen'
  | 'date'
  | 'liste_texte'
  | 'referentiel'
  | 'projet'

export interface ChampGabarit {
  nom: string
  type: TypeChamp
  description: string | null
  /** Liste dans laquelle puiser, quand le champ désigne un référentiel. */
  referentiel: ReferentielType | null
}

/** Champs qu'un gabarit peut préremplir, lus sur le schéma de création. */
export interface ChampsGabarit {
  entite: GabaritEntite
  champs: ChampGabarit[]
  cles_politique: string[]
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

// ─── Rapports de fin de journée ───

export type ReportItemSource = 'action' | 'manual'

export interface ReportItem {
  id: Uuid
  action_id: Uuid | null
  source: ReportItemSource
  label: string
  done: boolean
  position: number
}

export interface DailyReport {
  id: Uuid
  user_id: Uuid
  user_display_name: string | null
  report_date: IsoDate
  note: string | null
  submitted_at: IsoDateTime | null
  items: ReportItem[]
  created_at: IsoDateTime
  updated_at: IsoDateTime
}

export const SUGGESTION_REASONS = ['deadline_today', 'touched_today', 'carry_over'] as const
export type SuggestionReasonCode = (typeof SUGGESTION_REASONS)[number]

/**
 * Motif pour lequel une action est proposée à la déclaration.
 *
 * `label` vient du serveur : un code inconnu d'une version plus récente reste
 * affichable, faute de quoi l'interface tomberait sur une case vide.
 */
export interface SuggestionReason {
  code: SuggestionReasonCode
  label: string
}

export interface ReportSuggestion {
  action_id: Uuid
  numero: string
  description: string
  project_code: string | null
  progress: number
  deadline: IsoDate | null
  reasons: SuggestionReason[]
  already_added: boolean
}

export interface TodayReport {
  report_date: IsoDate
  report: DailyReport | null
  suggestions: ReportSuggestion[]
  /** Au moins une ligne ou une note — c'est ce qui fait taire le rappel. */
  has_content: boolean
}

/** Ligne envoyée au serveur. `id` absent pour une ligne créée à l'instant. */
export interface ReportItemPayload {
  id?: Uuid
  action_id?: Uuid | null
  label: string
  done: boolean
}

export interface DailyReportPayload {
  items: ReportItemPayload[]
  note?: string | null
}

// ─── Pagination ───

/** Résultat d'une liste paginée : `total` vient de l'en-tête `X-Total-Count`. */
export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}
