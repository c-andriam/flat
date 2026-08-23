import { useEffect, useState, type RefObject } from 'react'

/**
 * Largeur intérieure d'un élément, suivie en direct.
 *
 * `clientWidth` et non `getBoundingClientRect().width` : la première exclut la
 * barre de défilement verticale, la seconde la compte. Dans une grille de
 * calendrier, cet écart d'une dizaine de pixels suffit à désaligner l'en-tête
 * du corps.
 */
export function useElementWidth(ref: RefObject<HTMLElement | null>): number {
  const [width, setWidth] = useState(0)

  useEffect(() => {
    const element = ref.current
    if (!element) return
    const update = () => setWidth(element.clientWidth)
    update()
    const observer = new ResizeObserver(update)
    observer.observe(element)
    return () => observer.disconnect()
  }, [ref])

  return width
}
