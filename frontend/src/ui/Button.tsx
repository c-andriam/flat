import { Link } from 'react-router-dom'
import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ReactNode } from 'react'

import { cn } from '@/lib/cn'
import { Spinner } from './Spinner'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'
export type ButtonSize = 'sm' | 'md'

const BASE =
  'inline-flex items-center justify-center gap-2 rounded-[6px] border font-semibold leading-tight ' +
  'transition-[background-color,border-color,color,box-shadow,transform] duration-150 ' +
  'disabled:cursor-not-allowed disabled:opacity-55 active:translate-y-px cursor-pointer'

const VARIANTS: Record<ButtonVariant, string> = {
  primary: 'bg-success text-white border-black/15 hover:bg-success-hover',
  secondary: 'bg-surface text-fg border-line hover:bg-surface-hover hover:border-fg-subtle',
  ghost: 'bg-transparent text-fg-muted border-transparent hover:bg-surface-hover hover:text-fg',
  danger: 'bg-transparent text-danger border-line hover:bg-danger-subtle hover:border-danger',
}

const SIZES: Record<ButtonSize, string> = {
  sm: 'px-3 py-1.5 text-[13px]',
  md: 'px-5 py-2.5 text-sm',
}

interface CommonProps {
  variant?: ButtonVariant
  size?: ButtonSize
  loading?: boolean
  children?: ReactNode
  className?: string
}

export type ButtonProps = CommonProps & ButtonHTMLAttributes<HTMLButtonElement>

export function Button({
  variant = 'secondary',
  size = 'md',
  loading = false,
  className,
  children,
  disabled,
  ...props
}: ButtonProps) {
  return (
    <button
      type="button"
      className={cn(BASE, VARIANTS[variant], SIZES[size], className)}
      disabled={disabled ?? loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading ? <Spinner size={size === 'sm' ? 13 : 15} /> : null}
      {children}
    </button>
  )
}

export type LinkButtonProps = CommonProps & { to: string } & Omit<
    AnchorHTMLAttributes<HTMLAnchorElement>,
    'href'
  >

/** Même apparence que `Button`, mais navigation SPA (pas de rechargement). */
export function LinkButton({
  to,
  variant = 'secondary',
  size = 'md',
  className,
  children,
  ...props
}: LinkButtonProps) {
  return (
    <Link
      to={to}
      className={cn(BASE, VARIANTS[variant], SIZES[size], 'no-underline', className)}
      {...props}
    >
      {children}
    </Link>
  )
}

export type ExternalLinkButtonProps = CommonProps & AnchorHTMLAttributes<HTMLAnchorElement>

/** Pour les sorties hors SPA (SSO Microsoft) : rechargement plein écran voulu. */
export function ExternalLinkButton({
  variant = 'secondary',
  size = 'md',
  className,
  children,
  ...props
}: ExternalLinkButtonProps) {
  return (
    <a className={cn(BASE, VARIANTS[variant], SIZES[size], 'no-underline', className)} {...props}>
      {children}
    </a>
  )
}
