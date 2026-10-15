// Pure presentation helpers for the inbox UI: stable color tones, compact
// Chinese time labels, and thread grouping. All dates use the browser's local
// time zone; callers pass `now` so labels stay deterministic in tests.

export const AVATAR_TONE_COUNT = 8
const CONTINUATION_GAP_MS = 5 * 60_000
const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
const CHANNEL_TONES = new Map([
  ['qq', 'blue'],
  ['微信', 'green'],
  ['wechat', 'green'],
  ['邮箱', 'amber'],
  ['email', 'amber'],
  ['短信', 'purple'],
  ['sms', 'purple'],
  ['语音', 'teal'],
  ['voice', 'teal'],
  ['webhook', 'slate'],
])
const FALLBACK_CHANNEL_TONES = ['indigo', 'rose', 'olive', 'teal', 'purple', 'slate']

export function stableHash(value) {
  let hash = 0x811c9dc5
  for (const char of String(value ?? '')) {
    hash ^= char.codePointAt(0)
    hash = Math.imul(hash, 0x01000193) >>> 0
  }
  return hash
}

export function channelTone(label) {
  const key = String(label || '').trim().toLowerCase()
  return CHANNEL_TONES.get(key) || FALLBACK_CHANNEL_TONES[stableHash(key) % FALLBACK_CHANNEL_TONES.length]
}

export function avatarTone(seed) {
  return stableHash(String(seed || '').trim()) % AVATAR_TONE_COUNT
}

export function channelGlyph(label) {
  const text = String(label || '').trim()
  if (/^[\x21-\x7e]+$/.test(text)) return text.slice(0, 2).toUpperCase() || '?'
  return [...text][0] || '?'
}

function toDate(value) {
  if (value === null || value === undefined || value === '') return null
  const date = value instanceof Date ? new Date(value.valueOf()) : new Date(value)
  return Number.isNaN(date.valueOf()) ? null : date
}

function pad(value) {
  return String(value).padStart(2, '0')
}

function startOfDay(date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).valueOf()
}

function dayDifference(date, now) {
  return Math.round((startOfDay(now) - startOfDay(date)) / 86_400_000)
}

export function dayKey(value) {
  const date = toDate(value)
  return date ? `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` : ''
}

export function formatClock(value) {
  const date = toDate(value)
  return date ? `${pad(date.getHours())}:${pad(date.getMinutes())}` : ''
}

export function formatFullStamp(value) {
  const date = toDate(value)
  return date ? `${dayKey(date)} ${formatClock(date)}` : ''
}

function formatCalendarDate(date, now) {
  return date.getFullYear() === now.getFullYear()
    ? `${date.getMonth() + 1}月${date.getDate()}日`
    : `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日`
}

export function formatListTime(value, nowValue = new Date()) {
  const date = toDate(value)
  const now = toDate(nowValue) || new Date()
  if (!date) return ''
  const elapsed = now.valueOf() - date.valueOf()
  const days = dayDifference(date, now)
  if (days === 0 && elapsed >= -60_000 && elapsed < 60_000) return '刚刚'
  if (days === 0 && elapsed > 0 && elapsed < 3_600_000) return `${Math.floor(elapsed / 60_000)} 分钟前`
  if (days === 0) return formatClock(date)
  if (days === 1) return '昨天'
  if (days > 1 && days < 7) return WEEKDAYS[date.getDay()]
  return formatCalendarDate(date, now)
}

export function formatRelativeAge(value, nowValue = new Date()) {
  const date = toDate(value)
  const now = toDate(nowValue) || new Date()
  if (!date) return ''
  const elapsed = Math.max(0, now.valueOf() - date.valueOf())
  if (elapsed < 60_000) return '刚刚'
  if (elapsed < 3_600_000) return `${Math.floor(elapsed / 60_000)} 分钟前`
  if (elapsed < 86_400_000) return `${Math.floor(elapsed / 3_600_000)} 小时前`
  if (elapsed < 30 * 86_400_000) return `${Math.floor(elapsed / 86_400_000)} 天前`
  return formatCalendarDate(date, now)
}

export function formatDayLabel(value, nowValue = new Date()) {
  const date = toDate(value)
  const now = toDate(nowValue) || new Date()
  if (!date) return ''
  const days = dayDifference(date, now)
  if (days === 0) return '今天'
  if (days === 1) return '昨天'
  return `${formatCalendarDate(date, now)} ${WEEKDAYS[date.getDay()]}`
}

function senderKey(message) {
  return [message.direction, message.authorRole || '', message.senderName || ''].join('\u0000')
}

// Inserts a day separator before the first message of each local day and marks
// a message as a continuation when the same sender wrote the previous message
// on that day less than five minutes earlier.
export function buildThreadEntries(messages, nowValue = new Date()) {
  const entries = []
  let previous = null
  let previousDay = ''
  let previousTime = 0
  for (const message of messages) {
    const date = toDate(message.occurredAt)
    const day = dayKey(date)
    if (day && day !== previousDay) {
      entries.push({ kind: 'day', key: `day:${day}`, dateTime: day, label: formatDayLabel(date, nowValue) })
      previous = null
    }
    const time = date ? date.valueOf() : 0
    const continuation = Boolean(previous && date && senderKey(previous) === senderKey(message)
      && time >= previousTime && time - previousTime < CONTINUATION_GAP_MS)
    entries.push({ kind: 'message', key: message.id, message, continuation })
    previous = message
    previousDay = day || previousDay
    previousTime = time
  }
  return entries
}
