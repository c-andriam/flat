import { useActionSummary } from '@/api/queries'
import { useAuth } from '@/auth/useAuth'
import { usePortfolioReport } from '@/api/queries'
import { LinkButton } from '@/ui/Button'
import { IconActivity, IconAlert, IconClock, IconFolder, IconGrid } from '@/ui/Icon'
import { StatCard, StatGrid } from '@/ui/StatCard'

export function HomePage() {
  const { isAuthenticated, user } = useAuth()
  const summaryQuery = useActionSummary()
  const portfolioQuery = usePortfolioReport('active')

  // Les compteurs ne sont demandés qu'une fois la session établie : sans
  // jeton, les appels partiraient pour revenir en 401.
  const loading = isAuthenticated && (summaryQuery.isLoading || portfolioQuery.isLoading)
  const counts = summaryQuery.data?.counts
  const value = (key: string) => (isAuthenticated ? (counts?.[key] ?? 0) : '—')

  return (
    <div className="w-full text-center">
      <h1 className="animate-fade-in mb-3 text-[clamp(26px,4.5vw,40px)] font-extrabold leading-tight tracking-[-0.03em]">
        {user ? `Bonjour ${user.display_name.split(' ')[0]}` : 'Bienvenue sur votre espace de pilotage'}
      </h1>

      <p className="animate-fade-in mx-auto mb-10 max-w-[520px] text-[clamp(14px,2.2vw,17px)] leading-[1.7] text-fg-muted">
        Suivez l'avancement de vos projets, gérez les actions correctives et anticipez les échéances
        depuis une interface centralisée.
      </p>

      <div className="animate-fade-in mb-0 flex flex-wrap justify-center gap-3">
        <LinkButton to="/projets" variant="primary">
          <IconFolder size={16} />
          Accéder aux projets
        </LinkButton>
        <LinkButton to="/tableau-de-bord" variant="secondary">
          <IconGrid size={16} />
          Tableau de bord
        </LinkButton>
      </div>

      <div className="my-12 h-px w-full bg-line transition-colors" />

      <StatGrid>
        <StatCard
          label="Projets actifs"
          value={isAuthenticated ? (portfolioQuery.data?.project_count ?? 0) : '—'}
          tone="blue"
          loading={loading}
          icon={<IconFolder size={18} />}
        />
        <StatCard
          label="Actions en cours"
          value={value('in_progress')}
          tone="green"
          loading={loading}
          icon={<IconActivity size={18} />}
        />
        <StatCard
          label="Actions en retard"
          value={value('overdue')}
          tone="orange"
          loading={loading}
          icon={<IconAlert size={18} />}
        />
        <StatCard
          label="Échéances proches"
          value={value('due_soon')}
          tone="red"
          loading={loading}
          icon={<IconClock size={18} />}
        />
      </StatGrid>

      {!isAuthenticated ? (
        <p className="mt-8 text-[13px] text-fg-subtle">
          Connectez-vous avec votre compte Microsoft pour afficher les indicateurs en temps réel.
        </p>
      ) : null}
    </div>
  )
}
