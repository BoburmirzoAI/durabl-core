import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

/** Tailwind klasslarini birlashtiradi va ziddiyatlarni hal qiladi. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}
