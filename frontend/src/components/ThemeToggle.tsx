import { useTheme } from '@/theme/useTheme'
import { IconMoon, IconSun } from '@/ui/Icon'

export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme()
  const isDark = theme === 'dark'

  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-label={isDark ? 'Passer au thème clair' : 'Passer au thème sombre'}
      title={isDark ? 'Thème clair' : 'Thème sombre'}
      className="flex h-9 w-9 cursor-pointer items-center justify-center rounded-[6px] border border-line bg-transparent text-fg-muted transition-all duration-200 hover:-translate-y-px hover:border-fg-subtle hover:bg-surface-hover hover:text-fg active:translate-y-px active:scale-95"
    >
      {isDark ? <IconSun size={18} /> : <IconMoon size={18} />}
    </button>
  )
}
