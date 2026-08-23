import { useAuth } from '@/auth/useAuth'
import { IconAlert } from '@/ui/Icon'

/**
 * Bandeau affiché à un compte cloisonné qu'aucune fiche responsable ne
 * rattache.
 *
 * Sans lui, la personne verrait des écrans vides sans savoir pourquoi et
 * conclurait à une panne — alors que le portefeuille est simplement, et
 * volontairement, hors de sa portée.
 */
export function UnlinkedNotice() {
  const { isUnlinked, user } = useAuth()
  if (!isUnlinked) return null

  return (
    <div className="mb-5 flex items-start gap-3 rounded-[8px] border border-warning/30 bg-warning-subtle px-4 py-3">
      <IconAlert size={17} className="mt-0.5 shrink-0 text-warning" />
      <div className="min-w-0 text-[13px] leading-relaxed">
        <p className="font-semibold text-warning">Compte non rattaché</p>
        <p className="mt-0.5 text-fg-muted">
          Aucune fiche responsable ne porte l'adresse{' '}
          <span className="font-medium text-fg">{user?.email}</span>. Vos projets et vos
          actions resteront donc vides. Demandez à un administrateur d'associer votre adresse
          à votre fiche — c'est le même rattachement qui conditionne l'envoi des relances.
        </p>
      </div>
    </div>
  )
}
