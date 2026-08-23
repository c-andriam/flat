import type { ComponentType } from 'react'

import {
  IconActivity,
  IconCalendar,
  IconCalendarPlus,
  IconFolder,
  IconGrid,
  IconClipboard,
  IconPieChart,
  IconUsers,
  type IconProps,
} from '@/ui/Icon'

export interface NavEntry {
  to: string
  label: string
  icon: ComponentType<IconProps>
  /** Utilisé par la palette de commandes pour élargir la recherche. */
  keywords: string[]
}

export const NAV_ENTRIES: readonly NavEntry[] = [
  { to: '/tableau-de-bord', label: "Vue d'ensemble", icon: IconGrid, keywords: ['dashboard', 'accueil', 'kpi'] },
  { to: '/projets', label: 'Projets', icon: IconFolder, keywords: ['project', 'portefeuille', 'chantier'] },
  { to: '/actions', label: 'Actions', icon: IconActivity, keywords: ['tâches', 'todo', 'retard'] },
  { to: '/agenda', label: 'Agenda', icon: IconCalendar, keywords: ['calendrier', 'mois', 'fériés'] },
  { to: '/responsables', label: 'Responsables', icon: IconUsers, keywords: ['équipe', 'personnes', 'charge'] },
  { to: '/rapports', label: 'Rapports', icon: IconPieChart, keywords: ['reporting', 'export', 'indicateurs'] },
  { to: '/creneaux', label: 'Créneaux', icon: IconCalendarPlus, keywords: ['slots', 'disponibilités', 'semaine'] },
  {
    to: '/rapport-du-jour',
    label: 'Rapport du jour',
    icon: IconClipboard,
    keywords: ['fin de journée', 'compte rendu', 'tâches', 'daily'],
  },
] as const
