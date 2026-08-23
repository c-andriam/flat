import { useEffect, useRef } from 'react'

export interface HotkeyOptions {
  /** Touche telle que rapportée par `KeyboardEvent.key`, insensible à la casse. */
  key: string
  ctrlOrMeta?: boolean
  shift?: boolean
  enabled?: boolean
  /** Déclencher même quand le focus est dans un champ de saisie. */
  allowInInput?: boolean
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  const tag = target.tagName
  return (
    tag === 'INPUT' ||
    tag === 'TEXTAREA' ||
    tag === 'SELECT' ||
    target.isContentEditable
  )
}

/** Raccourci clavier global. */
export function useHotkey(options: HotkeyOptions, handler: (event: KeyboardEvent) => void): void {
  const { key, ctrlOrMeta = false, shift = false, enabled = true, allowInInput = false } = options
  // Le handler change à chaque rendu : le garder dans une ref évite de
  // détacher/rattacher l'écouteur global à chaque fois.
  const handlerRef = useRef(handler)
  handlerRef.current = handler

  useEffect(() => {
    if (!enabled) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() !== key.toLowerCase()) return
      if (ctrlOrMeta !== (event.ctrlKey || event.metaKey)) return
      if (shift !== event.shiftKey) return
      if (!allowInInput && isEditableTarget(event.target)) return
      handlerRef.current(event)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [key, ctrlOrMeta, shift, enabled, allowInInput])
}
