import { useEffect } from 'react'

/**
 * Verrou de défilement partagé par les overlays.
 *
 * Un compteur plutôt qu'un booléen : si une modale ouvre une palette,
 * la fermeture de la seconde ne doit pas déverrouiller la page.
 */
let lockCount = 0

export function useScrollLock(active: boolean): void {
  useEffect(() => {
    if (!active) return
    lockCount += 1
    document.body.dataset.scrollLocked = 'true'
    return () => {
      lockCount -= 1
      if (lockCount <= 0) {
        lockCount = 0
        delete document.body.dataset.scrollLocked
      }
    }
  }, [active])
}
