import { LinkButton } from '@/ui/Button'
import { EmptyState } from '@/ui/EmptyState'
import { IconSearch } from '@/ui/Icon'

export function NotFoundPage() {
  return (
    <div className="w-full max-w-[520px]">
      <EmptyState
        icon={<IconSearch size={44} strokeWidth={1.5} />}
        title="Page introuvable"
        message="L'adresse demandée ne correspond à aucun écran de l'application."
        action={
          <LinkButton to="/" variant="primary" size="sm">
            Revenir à l'accueil
          </LinkButton>
        }
      />
    </div>
  )
}
