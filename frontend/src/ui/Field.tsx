import { useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react'

import { cn } from '@/lib/cn'

const CONTROL =
  'w-full rounded-[6px] border border-line bg-canvas px-3 py-2.5 text-sm text-fg ' +
  'outline-none transition-colors placeholder:text-fg-subtle ' +
  'focus:border-accent focus:ring-2 focus:ring-accent/20 ' +
  'disabled:cursor-not-allowed disabled:bg-inset disabled:opacity-60'

function FieldShell({
  id,
  label,
  hint,
  error,
  required,
  children,
  className,
}: {
  id: string
  label?: ReactNode
  hint?: ReactNode
  error?: string | null
  required?: boolean
  children: ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      {label ? (
        <label htmlFor={id} className="text-[13px] font-medium text-fg-muted">
          {label}
          {required ? <span className="ml-1 text-danger">*</span> : null}
        </label>
      ) : null}
      {children}
      {error ? (
        <p className="text-[12px] font-medium text-danger">{error}</p>
      ) : hint ? (
        <p className="text-[12px] text-fg-subtle">{hint}</p>
      ) : null}
    </div>
  )
}

export interface TextFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'className'> {
  label?: ReactNode
  hint?: ReactNode
  error?: string | null
  className?: string
}

export function TextField({ label, hint, error, className, required, ...props }: TextFieldProps) {
  const generatedId = useId()
  const id = props.id ?? generatedId
  return (
    <FieldShell id={id} label={label} hint={hint} error={error} required={required} className={className}>
      <input
        id={id}
        required={required}
        aria-invalid={error ? true : undefined}
        className={cn(CONTROL, error && 'border-danger focus:border-danger focus:ring-danger/20')}
        {...props}
      />
    </FieldShell>
  )
}

export interface TextAreaFieldProps
  extends Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'className'> {
  label?: ReactNode
  hint?: ReactNode
  error?: string | null
  className?: string
}

export function TextAreaField({
  label,
  hint,
  error,
  className,
  required,
  rows = 3,
  ...props
}: TextAreaFieldProps) {
  const generatedId = useId()
  const id = props.id ?? generatedId
  return (
    <FieldShell id={id} label={label} hint={hint} error={error} required={required} className={className}>
      <textarea
        id={id}
        rows={rows}
        required={required}
        aria-invalid={error ? true : undefined}
        className={cn(CONTROL, 'resize-y', error && 'border-danger focus:border-danger focus:ring-danger/20')}
        {...props}
      />
    </FieldShell>
  )
}

export interface SelectOption<T extends string = string> {
  value: T
  label: string
}

export interface SelectFieldProps<T extends string = string>
  extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'className' | 'children'> {
  label?: ReactNode
  hint?: ReactNode
  error?: string | null
  className?: string
  options: readonly SelectOption<T>[]
}

export function SelectField<T extends string = string>({
  label,
  hint,
  error,
  className,
  options,
  required,
  ...props
}: SelectFieldProps<T>) {
  const generatedId = useId()
  const id = props.id ?? generatedId
  return (
    <FieldShell id={id} label={label} hint={hint} error={error} required={required} className={className}>
      <select
        id={id}
        required={required}
        aria-invalid={error ? true : undefined}
        className={cn(CONTROL, 'cursor-pointer appearance-none pr-9', error && 'border-danger')}
        style={{
          backgroundImage:
            "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%238b949e' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E\")",
          backgroundRepeat: 'no-repeat',
          backgroundPosition: 'right 10px center',
        }}
        {...props}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </FieldShell>
  )
}
