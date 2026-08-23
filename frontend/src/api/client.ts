/**
 * Client HTTP typé vers la gateway.
 *
 * Un seul point d'entrée pour : l'injection du jeton Bearer, la
 * normalisation des erreurs FastAPI (`{"detail": …}`), et la lecture de
 * l'en-tête `X-Total-Count` que renvoient toutes les routes de liste.
 */

import type { Page } from './types'

const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')
const API_PREFIX = `${BASE_URL}/api/v1`

const TOKEN_STORAGE_KEY = 'dsio-token'

let memoryToken: string | null = null

/** Appelé quand le serveur rejette le jeton — branché sur le contexte d'auth. */
type UnauthorizedHandler = () => void
let onUnauthorized: UnauthorizedHandler | null = null

export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  onUnauthorized = handler
}

export function getToken(): string | null {
  if (memoryToken !== null) return memoryToken
  try {
    memoryToken = window.localStorage.getItem(TOKEN_STORAGE_KEY)
  } catch {
    // Navigation privée : le jeton ne survivra pas au rechargement, mais la
    // session en cours doit rester utilisable.
    memoryToken = null
  }
  return memoryToken
}

export function setToken(token: string | null): void {
  memoryToken = token
  try {
    if (token === null) window.localStorage.removeItem(TOKEN_STORAGE_KEY)
    else window.localStorage.setItem(TOKEN_STORAGE_KEY, token)
  } catch {
    /* Stockage indisponible : on garde le jeton en mémoire uniquement. */
  }
}

export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown

  constructor(status: number, message: string, detail: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }

  /** Vrai quand la ressource n'existe pas — utile pour afficher un état vide. */
  get isNotFound(): boolean {
    return this.status === 404
  }

  get isAuthError(): boolean {
    return this.status === 401 || this.status === 403
  }
}

export type QueryValue = string | number | boolean | null | undefined
export type QueryParams = Record<string, QueryValue | QueryValue[]>

function buildUrl(path: string, query?: QueryParams): string {
  const url = `${API_PREFIX}${path}`
  if (!query) return url
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === null || value === undefined || value === '') continue
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item === null || item === undefined || item === '') continue
        search.append(key, String(item))
      }
    } else {
      search.append(key, String(value))
    }
  }
  const qs = search.toString()
  return qs ? `${url}?${qs}` : url
}

/** Aplatit les erreurs de validation Pydantic en une phrase lisible. */
function messageFromDetail(status: number, detail: unknown): string {
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const parts = detail
      .map((entry) => {
        if (typeof entry !== 'object' || entry === null) return null
        const record = entry as { loc?: unknown[]; msg?: unknown }
        const field = Array.isArray(record.loc) ? record.loc.slice(1).join('.') : ''
        const msg = typeof record.msg === 'string' ? record.msg : ''
        return field ? `${field} : ${msg}` : msg
      })
      .filter((part): part is string => Boolean(part))
    if (parts.length > 0) return parts.join(' · ')
  }
  if (status === 401) return 'Session expirée, veuillez vous reconnecter.'
  if (status === 403) return "Votre rôle ne permet pas cette opération."
  if (status === 404) return 'Ressource introuvable.'
  if (status >= 500) return 'Le serveur a rencontré une erreur. Réessayez dans un instant.'
  return `Erreur ${status}.`
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  query?: QueryParams
  body?: unknown
  signal?: AbortSignal
}

async function rawRequest(path: string, options: RequestOptions = {}): Promise<Response> {
  const { method = 'GET', query, body, signal } = options

  const headers: Record<string, string> = { Accept: 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  let response: Response
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: signal ?? null,
    })
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause
    // `fetch` ne rejette que sur une panne réseau : la distinguer d'un 5xx
    // évite d'afficher « erreur serveur » quand c'est le Wi-Fi qui est tombé.
    throw new ApiError(0, 'Serveur injoignable. Vérifiez votre connexion.', cause)
  }

  if (response.ok) return response

  let detail: unknown = null
  try {
    const payload = (await response.json()) as { detail?: unknown }
    detail = payload?.detail ?? payload
  } catch {
    detail = await response.text().catch(() => null)
  }

  if (response.status === 401) {
    setToken(null)
    onUnauthorized?.()
  }

  throw new ApiError(response.status, messageFromDetail(response.status, detail), detail)
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await rawRequest(path, options)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

/** Variante des routes DELETE, qui répondent 204 sans corps. */
export async function requestVoid(path: string, options: RequestOptions = {}): Promise<void> {
  await rawRequest(path, options)
}

/** Liste paginée : associe le corps JSON au total renvoyé par l'en-tête. */
export async function requestPage<T>(path: string, options: RequestOptions = {}): Promise<Page<T>> {
  const response = await rawRequest(path, options)
  const items = (await response.json()) as T[]
  const header = response.headers.get('X-Total-Count')
  const total = header !== null && header !== '' ? Number(header) : items.length
  const query = options.query ?? {}
  return {
    items,
    total: Number.isFinite(total) ? total : items.length,
    limit: Number(query.limit ?? items.length),
    offset: Number(query.offset ?? 0),
  }
}

/** URL de redirection vers le SSO Microsoft (navigation plein écran). */
export function loginUrl(): string {
  return `${API_PREFIX}/auth/login`
}

/** URL du hub temps réel, jeton inclus (les WebSockets n'ont pas d'en-têtes). */
export function websocketUrl(token: string): string {
  const configured = import.meta.env.VITE_WS_URL
  if (configured) return `${configured}?token=${encodeURIComponent(token)}`
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/ws?token=${encodeURIComponent(token)}`
}
