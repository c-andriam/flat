/**
 * Mises à jour optimistes : l'interface répond avant le serveur.
 *
 * La base est distante (Supabase) et l'aller-retour coûte environ 250 ms
 * depuis Madagascar. Une case à cocher qui attend la réponse avant de se
 * cocher donne une interface qui « colle », et un utilisateur qui reclique —
 * donc deux requêtes pour une intention.
 *
 * Le principe : on applique le changement dans le cache immédiatement, on
 * garde une photo de l'état précédent, et on la restaure si le serveur refuse.
 * La notification, elle, n'est affichée qu'à la réponse : annoncer un succès
 * avant de l'avoir obtenu serait mentir une fois sur cent.
 *
 * Ce module ne connaît que la forme des données mises en cache. Les trois
 * formes en circulation dans l'application sont traversées :
 *
 *   - une page       `{ items: [...], total, limit, offset }`
 *   - un tableau nu  `[...]`
 *   - un objet seul  `{ id, ... }`
 *
 * Écrire un transformateur par appelant aurait signifié réécrire ce parcours
 * à chaque hook, et l'oublier sur la forme la moins fréquente.
 */

import type { QueryClient, QueryKey } from '@tanstack/react-query'

import type { Uuid } from './types'

/** De quoi revenir à l'état d'avant si le serveur refuse. */
export interface Rollback {
  restaurer: () => void
}

/** Rollback inerte — pour les cas où rien n'a été modifié localement. */
export const SANS_ROLLBACK: Rollback = { restaurer: () => {} }

interface PageLike {
  items: unknown[]
}

function estUnePage(valeur: unknown): valeur is PageLike {
  return (
    typeof valeur === 'object' &&
    valeur !== null &&
    Array.isArray((valeur as PageLike).items)
  )
}

/**
 * Nom du champ qui identifie une entité dans le cache.
 *
 * `id` couvre presque tout, mais pas les réglages de relance : ils sont
 * identifiés par `responsable_id`, la préférence n'ayant pas d'existence
 * propre en dehors de la personne qu'elle concerne.
 */
export type ChampCle = string

function aLIdentifiant(valeur: unknown, id: Uuid, champ: ChampCle): boolean {
  return (
    typeof valeur === 'object' &&
    valeur !== null &&
    (valeur as Record<string, unknown>)[champ] === id
  )
}

/**
 * Applique `patch` à l'entité `id`, où qu'elle se trouve dans une valeur mise
 * en cache. Renvoie la valeur inchangée — la même référence — si l'entité n'y
 * figure pas : React ne re-rend alors pas les composants qui en dépendent.
 */
function patcherValeur<T extends object>(
  valeur: unknown,
  id: Uuid,
  patch: Partial<T>,
  champ: ChampCle,
): unknown {
  if (valeur === undefined || valeur === null) return valeur

  if (Array.isArray(valeur)) {
    let touche = false
    const suivant = valeur.map((element) => {
      if (!aLIdentifiant(element, id, champ)) return element
      touche = true
      return { ...(element as object), ...patch }
    })
    return touche ? suivant : valeur
  }

  if (estUnePage(valeur)) {
    const items = patcherValeur(valeur.items, id, patch, champ)
    return items === valeur.items ? valeur : { ...valeur, items }
  }

  if (aLIdentifiant(valeur, id, champ)) return { ...(valeur as object), ...patch }

  return valeur
}

/**
 * Modifie une entité dans toutes les entrées de cache d'un préfixe.
 *
 * `cancelQueries` d'abord : une requête déjà en vol reviendrait avec les
 * anciennes données et écraserait la mise à jour optimiste quelques
 * millisecondes après l'avoir appliquée — le défaut se voit à l'œil nu, la
 * case se décoche toute seule.
 */
export async function patcherEntite<T extends object>(
  client: QueryClient,
  prefixe: QueryKey,
  id: Uuid,
  patch: Partial<T>,
  champ: ChampCle = 'id',
): Promise<Rollback> {
  await client.cancelQueries({ queryKey: prefixe })
  const precedent = client.getQueriesData({ queryKey: prefixe })
  client.setQueriesData({ queryKey: prefixe }, (valeur: unknown) =>
    patcherValeur<T>(valeur, id, patch, champ),
  )
  return {
    restaurer: () => {
      for (const [cle, valeur] of precedent) client.setQueryData(cle, valeur)
    },
  }
}

/**
 * Retire une entité de toutes les entrées de cache d'un préfixe.
 *
 * Les totaux de pagination sont décrémentés : sans cela, une liste de 25
 * éléments sur 25 afficherait « 25 » au-dessus de 24 lignes, jusqu'à la
 * réponse du serveur.
 */
export async function retirerEntite(
  client: QueryClient,
  prefixe: QueryKey,
  id: Uuid,
): Promise<Rollback> {
  await client.cancelQueries({ queryKey: prefixe })
  const precedent = client.getQueriesData({ queryKey: prefixe })

  const retirer = (valeur: unknown): unknown => {
    if (valeur === undefined || valeur === null) return valeur
    if (Array.isArray(valeur)) {
      const suivant = valeur.filter((element) => !aLIdentifiant(element, id, 'id'))
      return suivant.length === valeur.length ? valeur : suivant
    }
    if (estUnePage(valeur)) {
      const items = retirer(valeur.items) as unknown[]
      if (items === valeur.items) return valeur
      const total = (valeur as { total?: number }).total
      return {
        ...valeur,
        items,
        ...(typeof total === 'number' ? { total: Math.max(0, total - 1) } : {}),
      }
    }
    return valeur
  }

  client.setQueriesData({ queryKey: prefixe }, retirer)
  return {
    restaurer: () => {
      for (const [cle, valeur] of precedent) client.setQueryData(cle, valeur)
    },
  }
}

/**
 * Modifie l'objet stocké sous une clé précise.
 *
 * Pour les ressources qui ne sont pas identifiées par un `id` dans leur
 * cache — les réglages de relance du compte courant, par exemple, rangés
 * sous une clé fixe.
 */
export async function patcherObjet<T extends object>(
  client: QueryClient,
  cle: QueryKey,
  patch: Partial<T>,
): Promise<Rollback> {
  await client.cancelQueries({ queryKey: cle })
  const precedent = client.getQueryData<T>(cle)
  if (precedent === undefined) return SANS_ROLLBACK
  client.setQueryData<T>(cle, { ...precedent, ...patch })
  return { restaurer: () => client.setQueryData<T>(cle, precedent) }
}
