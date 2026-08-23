import { useIsFetching } from '@tanstack/react-query'
import { useNavigation } from 'react-router-dom'

import { cn } from '@/lib/cn'

/**
 * Barre de progression fine en haut de page.
 *
 * Remplace le `.spa-loader` piloté par htmx : elle s'allume dès qu'une
 * navigation ou une requête est en vol, ce qui couvre aussi les
 * rafraîchissements déclenchés par le temps réel.
 */
export function RouteProgress() {
  const navigation = useNavigation()
  /**
   * Seuls les chargements initiaux comptent.
   *
   * Une requête qui a déjà des données en cache est un rafraîchissement de
   * fond : la faire clignoter en haut de l'écran donnait l'impression que
   * l'application ramait, alors que le contenu affiché était complet et à jour
   * — c'était particulièrement voyant sur la grille des créneaux, qui se
   * revalide à chaque geste.
   */
  const fetching = useIsFetching({ predicate: (query) => query.state.data === undefined })
  const active = navigation.state !== 'idle' || fetching > 0

  return (
    <div
      aria-hidden="true"
      className={cn(
        'pointer-events-none fixed inset-x-0 top-0 z-[9999] h-[3px] overflow-hidden transition-opacity duration-200',
        active ? 'opacity-100' : 'opacity-0',
      )}
    >
      {active ? <div className="animate-indeterminate h-full w-full bg-accent" /> : null}
    </div>
  )
}
