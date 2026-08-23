import { Component, type ErrorInfo, type ReactNode } from 'react'

import { Button } from '@/ui/Button'
import { EmptyState } from '@/ui/EmptyState'
import { IconAlert, IconRefresh } from '@/ui/Icon'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

/**
 * Filet de sécurité : une exception de rendu ne doit pas laisser une page
 * blanche sans moyen de repartir.
 */
export class ErrorBoundary extends Component<Props, State> {
  override state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('Erreur de rendu non rattrapée', error, info.componentStack)
  }

  override render(): ReactNode {
    const { error } = this.state
    if (!error) return this.props.children

    return (
      <div className="mx-auto w-full max-w-[640px] px-6 py-16">
        <EmptyState
          icon={<IconAlert size={44} strokeWidth={1.5} className="text-danger" />}
          title="Une erreur est survenue"
          message={error.message || "L'interface a rencontré un problème inattendu."}
          action={
            <Button variant="primary" onClick={() => window.location.reload()}>
              <IconRefresh size={15} />
              Recharger l'application
            </Button>
          }
        />
      </div>
    )
  }
}
