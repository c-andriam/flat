/**
 * Clés de cache centralisées.
 *
 * Les regrouper ici garantit qu'une invalidation (`['actions']`) atteint bien
 * toutes les variantes filtrées d'une liste : c'est ce que fait le hub temps
 * réel à chaque événement reçu.
 */

import type { ActionListParams, ProjectListParams, ResponsableListParams } from './endpoints'
import type { Uuid } from './types'

export const queryKeys = {
  me: ['me'] as const,

  projects: {
    all: ['projects'] as const,
    list: (params: ProjectListParams) => ['projects', 'list', params] as const,
    detail: (id: Uuid) => ['projects', 'detail', id] as const,
  },

  actions: {
    all: ['actions'] as const,
    list: (params: ActionListParams) => ['actions', 'list', params] as const,
    detail: (id: Uuid) => ['actions', 'detail', id] as const,
    summary: ['actions', 'summary'] as const,
  },

  responsables: {
    all: ['responsables'] as const,
    list: (params: ResponsableListParams) => ['responsables', 'list', params] as const,
    detail: (id: Uuid) => ['responsables', 'detail', id] as const,
  },

  reports: {
    all: ['reports'] as const,
    portfolio: (scope: 'active' | 'all') => ['reports', 'portfolio', scope] as const,
    project: (id: Uuid) => ['reports', 'project', id] as const,
    workload: (activeOnly: boolean) => ['reports', 'workload', activeOnly] as const,
    forecast: (params: object) => ['reports', 'forecast', params] as const,
  },

  relances: {
    all: ['relances'] as const,
    config: ['relances', 'config'] as const,
  },

  slots: {
    all: ['slots'] as const,
    list: (params: object) => ['slots', 'list', params] as const,
    owners: ['slots', 'owners'] as const,
    requests: (params: object) => ['slots', 'requests', params] as const,
  },

  dailyReports: {
    all: ['daily-reports'] as const,
    today: (day: string | undefined) => ['daily-reports', 'today', day ?? 'auto'] as const,
    history: (params: object) => ['daily-reports', 'history', params] as const,
  },

  logs: {
    sync: (limit: number) => ['logs', 'sync', limit] as const,
    relances: (limit: number) => ['logs', 'relances', limit] as const,
  },
} as const
