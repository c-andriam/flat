import { createBrowserRouter, Navigate } from 'react-router-dom'

import { CenteredLayout } from '@/components/layout/CenteredLayout'
import { DashboardLayout } from '@/components/layout/DashboardLayout'
import { RootLayout } from '@/components/layout/RootLayout'
import { ActionsPage } from '@/pages/ActionsPage'
import { AgendaPage } from '@/pages/AgendaPage'
import { DailyReportPage } from '@/pages/DailyReportPage'
import { DashboardPage } from '@/pages/DashboardPage'
import { HomePage } from '@/pages/HomePage'
import { LoginPage } from '@/pages/LoginPage'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { ProjectDetailPage } from '@/pages/ProjectDetailPage'
import { ProjectsPage } from '@/pages/ProjectsPage'
import { RapportsPage } from '@/pages/RapportsPage'
import { RelancesPage } from '@/pages/RelancesPage'
import { ResponsablesPage } from '@/pages/ResponsablesPage'
import { SlotsPage } from '@/pages/SlotsPage'

/**
 * Les URL sont en français et stables : celles de l'ancienne application
 * (`/dashboard`, `/projects`, `/slots`) redirigent, pour que les favoris et
 * les liens déjà partagés continuent de fonctionner.
 */
export const router = createBrowserRouter([
  {
    element: <RootLayout />,
    children: [
      {
        element: <CenteredLayout />,
        children: [
          { path: '/', element: <HomePage /> },
          { path: '/connexion', element: <LoginPage /> },
          { path: '*', element: <NotFoundPage /> },
        ],
      },
      {
        element: <DashboardLayout />,
        children: [
          { path: '/tableau-de-bord', element: <DashboardPage /> },
          { path: '/projets', element: <ProjectsPage /> },
          { path: '/projets/:projectId', element: <ProjectDetailPage /> },
          { path: '/actions', element: <ActionsPage /> },
          { path: '/agenda', element: <AgendaPage /> },
          { path: '/responsables', element: <ResponsablesPage /> },
          { path: '/relances', element: <RelancesPage /> },
          { path: '/rapports', element: <RapportsPage /> },
          { path: '/creneaux', element: <SlotsPage /> },
          { path: '/rapport-du-jour', element: <DailyReportPage /> },
        ],
      },
      // Anciennes routes du frontend Jinja.
      { path: '/dashboard', element: <Navigate to="/tableau-de-bord" replace /> },
      { path: '/projects', element: <Navigate to="/projets" replace /> },
      { path: '/rapports.html', element: <Navigate to="/rapports" replace /> },
      { path: '/slots', element: <Navigate to="/creneaux" replace /> },
    ],
  },
])
