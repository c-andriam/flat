import { createContext } from 'react'

import type { ApiError } from '@/api/client'
import type { CurrentUser, LinkedResponsable, UserRole } from '@/api/types'

export interface AuthContextValue {
  user: CurrentUser | null
  token: string | null
  /** Vrai tant que le profil n'a pas été résolu. */
  isLoading: boolean
  isAuthenticated: boolean
  error: ApiError | null
  /** Redirige vers le SSO Microsoft (navigation plein écran). */
  login: () => void
  logout: () => void
  /** Vrai si le rôle courant fait partie de ceux attendus. */
  hasRole: (...roles: UserRole[]) => boolean
  /** Raccourci : le rôle `lecteur` n'a aucun droit d'écriture. */
  canWrite: boolean
  /** Vrai si le compte voit l'ensemble du portefeuille (`admin`, `dsio`). */
  seesAllData: boolean
  /** Fiches responsable rattachées au compte, via l'email. */
  linkedResponsables: LinkedResponsable[]
  /** Identifiants de ces fiches, pour repérer « mes » actions d'un coup d'œil. */
  linkedResponsableIds: ReadonlySet<string>
  /**
   * Compte cloisonné et non rattaché : il ne verra rien tant qu'un
   * administrateur n'aura pas associé son adresse à une fiche responsable.
   */
  isUnlinked: boolean
}

/** Séparé du provider pour que le rafraîchissement à chaud reste opérant. */
export const AuthContext = createContext<AuthContextValue | null>(null)
