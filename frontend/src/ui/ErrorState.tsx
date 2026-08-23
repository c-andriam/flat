import { ApiError } from '@/api/client'
import { Button } from './Button'
import { EmptyState } from './EmptyState'
import { IconAlert, IconRefresh } from './Icon'

/** État d'échec homogène pour toutes les pages branchées sur l'API. */
export function ErrorState({
  error,
  onRetry,
  title = 'Chargement impossible',
}: {
  error: unknown
  onRetry?: () => void
  title?: string
}) {
  const message =
    error instanceof ApiError
      ? error.message
      : error instanceof Error
        ? error.message
        : 'Une erreur inattendue est survenue.'

  return (
    <EmptyState
      icon={<IconAlert size={44} strokeWidth={1.5} className="text-warning" />}
      title={title}
      message={message}
      action={
        onRetry ? (
          <Button variant="secondary" size="sm" onClick={onRetry}>
            <IconRefresh size={14} />
            Réessayer
          </Button>
        ) : undefined
      }
    />
  )
}
