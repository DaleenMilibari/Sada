import { ALL_DAYS } from './api';

// Plain-language name of a filter window, e.g. "آخر 30 يوماً" or "كل الفترة (95 يوماً)".
export function periodLabel(days: number, spanDays?: number | null): string {
  if (days < ALL_DAYS) return `آخر ${days} يوماً`;
  return spanDays ? `كل الفترة (${spanDays} يوماً)` : 'كل الفترة';
}
