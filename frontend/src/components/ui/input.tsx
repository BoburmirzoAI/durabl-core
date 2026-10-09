'use client'

import { forwardRef } from 'react'

import { cn } from '@/lib/utils/cn'

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {}

/** To'liq chegarali input (formalarda). */
export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, type = 'text', ...props }, ref) => (
    <input
      ref={ref}
      type={type}
      className={cn(
        'h-[34px] w-full rounded-lg border border-line bg-canvas-raised px-2.5 text-base text-fg',
        'placeholder:text-fg-faint',
        'transition-colors hover:border-line-hover focus:border-accent focus:outline-none',
        'disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      {...props}
    />
  ),
)
Input.displayName = 'Input'

export interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  /** Monospace (kod kiritish uchun). */
  mono?: boolean
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, mono = false, ...props }, ref) => (
    <textarea
      ref={ref}
      className={cn(
        'w-full rounded-lg border border-line bg-canvas-deep px-3 py-2.5 text-fg',
        'placeholder:text-fg-faint',
        'transition-colors hover:border-line-hover focus:border-accent focus:outline-none',
        mono ? 'font-mono text-sm leading-[1.7]' : 'text-base',
        className,
      )}
      {...props}
    />
  ),
)
Textarea.displayName = 'Textarea'

/**
 * Qidiruv maydoni — dizayndagi ko'rinish: konteyner chegarali, input esa
 * shaffof, yonida ikonka va ⌘ yorlig'i.
 */
export interface SearchFieldProps extends React.InputHTMLAttributes<HTMLInputElement> {
  /** O'ng tomonda ko'rsatiladigan klaviatura yorlig'i (`⌘F`). */
  shortcut?: string
  containerClassName?: string
}

export const SearchField = forwardRef<HTMLInputElement, SearchFieldProps>(
  ({ className, containerClassName, shortcut, ...props }, ref) => (
    <div
      className={cn(
        'flex items-center gap-2 rounded-lg border border-line bg-surface px-2.5 py-1.5',
        'transition-colors hover:border-line-hover',
        // Ichki input outline'ni bosadi, shuning uchun fokusni konteyner ko'rsatadi.
        // `line-hover` qo'shni fonga nisbatan 1.4:1 edi — amalda ko'rinmaydi.
        'focus-within:border-accent',
        containerClassName,
      )}
    >
      <svg
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        className="shrink-0 text-fg-faint"
        aria-hidden
      >
        <path d="M10 4a6 6 0 1 0 0 12 6 6 0 0 0 0-12zM20 20l-4.3-4.3" />
      </svg>
      <input ref={ref} className={cn('input-bare', className)} {...props} />
      {shortcut ? <span className="kbd shrink-0 text-2xs">{shortcut}</span> : null}
    </div>
  ),
)
SearchField.displayName = 'SearchField'
