export type ChannelTone = 'blue' | 'green' | 'amber' | 'purple' | 'teal' | 'slate' | 'indigo' | 'rose' | 'olive'

export type ThreadDayEntry = { kind: 'day', key: string, dateTime: string, label: string }
export type ThreadMessageEntry<T> = { kind: 'message', key: string, message: T, continuation: boolean }
export type ThreadEntry<T> = ThreadDayEntry | ThreadMessageEntry<T>

export const AVATAR_TONE_COUNT: number
export function stableHash(value: unknown): number
export function channelTone(label: unknown): ChannelTone
export function avatarTone(seed: unknown): number
export function channelGlyph(label: unknown): string
export function dayKey(value: unknown): string
export function formatClock(value: unknown): string
export function formatFullStamp(value: unknown): string
export function formatListTime(value: unknown, now?: Date | number | string): string
export function formatRelativeAge(value: unknown, now?: Date | number | string): string
export function formatDayLabel(value: unknown, now?: Date | number | string): string
export function buildThreadEntries<T extends {
  id: string
  direction: string
  senderName?: string | null
  authorRole?: string | null
  occurredAt?: string | null
}>(messages: T[], now?: Date | number | string): ThreadEntry<T>[]
