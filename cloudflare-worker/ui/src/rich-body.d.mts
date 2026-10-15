export type CardKind = 'miniprogram' | 'link' | 'app' | 'forward' | 'channels' | 'music' | 'location' | 'contact' | 'article'
export type MediaKind = 'image' | 'voice' | 'video' | 'file' | 'sticker' | 'unknown'
export type MoneyKind = 'transfer' | 'redpacket'

export type TextBlock = { type: 'text', text: string }
export type QuoteBlock = { type: 'quote', author: string, text: string }
export type CardBlock = { type: 'card', kind: CardKind, label: string, title: string, summary: string, source: string }
export type MoneyBlock = { type: 'money', kind: MoneyKind, label: string, amount: string, summary: string, status: string }
export type NoticeBlock = { type: 'notice', kind: 'pat', text: string }
export type MediaBlock = { type: 'media', kind: MediaKind, label: string }
export type MessageBlock = TextBlock | QuoteBlock | CardBlock | MoneyBlock | NoticeBlock | MediaBlock

export const CARD_LABELS: Record<CardKind, string>
export const MEDIA_LABELS: Record<MediaKind, string>
export const MONEY_LABELS: Record<MoneyKind, string>
export function parseTaggedLine(line: unknown): Exclude<MessageBlock, TextBlock> | null
export function parseMessageBody(value: unknown): MessageBlock[]
export function previewText(value: unknown): string
