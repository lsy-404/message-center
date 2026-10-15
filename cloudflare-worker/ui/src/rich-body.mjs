// Turns QQ/WeChat message text into display blocks. Adapters flatten native
// elements into tagged lines ("[卡片] 标题 · 摘要 · 来源", "[picture:alias]",
// "[reply:type-7]"), and native digests use the client's own tags
// ("[小程序]标题", "[QQ小程序]…"). A tag is structural only at the start of a
// line; anything unrecognized stays plain text. Message text is untrusted, so
// blocks carry plain strings only and are rendered as text, never as HTML.

export const CARD_LABELS = {
  miniprogram: '小程序',
  link: '链接',
  app: '卡片',
  forward: '聊天记录',
  channels: '视频号',
  music: '音乐',
  location: '位置',
  contact: '名片',
  article: '公众号',
}
export const MEDIA_LABELS = { image: '图片', voice: '语音', video: '视频', file: '文件', sticker: '表情', unknown: '消息' }
export const MONEY_LABELS = { transfer: '转账', redpacket: '红包' }

const CARD_TAGS = new Map([
  ['小程序', 'miniprogram'], ['qq小程序', 'miniprogram'], ['微信小程序', 'miniprogram'],
  ['链接', 'link'], ['分享', 'link'],
  ['卡片', 'app'],
  ['聊天记录', 'forward'], ['合并转发', 'forward'],
  ['视频号', 'channels'],
  ['音乐', 'music'],
  ['位置', 'location'],
  ['名片', 'contact'], ['个人名片', 'contact'],
  ['公众号', 'article'], ['文章', 'article'],
])
const MONEY_TAGS = new Map([['转账', 'transfer'], ['红包', 'redpacket']])
const MEDIA_TAGS = new Map([
  ['图片', 'image'], ['语音', 'voice'], ['视频', 'video'], ['文件', 'file'], ['表情', 'sticker'], ['动画表情', 'sticker'],
])
const PLACEHOLDER_KINDS = { picture: 'image', file: 'file', voice: 'voice', video: 'video', sticker: 'sticker' }
const QUOTE_TAGS = new Set(['引用', '回复'])
const NOTICE_TAGS = new Set(['拍一拍'])
const OPAQUE_KIND_LABELS = {
  ark: '卡片消息', face: '表情', 'gray-tip': '系统提示', markdown: 'Markdown 消息',
  'multi-forward': '聊天记录', forward: '聊天记录',
}
const OPAQUE_TYPE_LABELS = { 6: '表情', 8: '系统提示', 10: '卡片消息', 14: 'Markdown 消息', 16: '聊天记录' }

const TAG_LINE = /^\[([^[\]\n:]{1,12})\][ \t]*(.*)$/u
const PLACEHOLDER_LINE = /^\[(picture|file|voice|video|sticker):([^\]\n]*)\]$/u
const OPAQUE_LINE = /^\[([a-z][a-z0-9-]{0,30}):type-(\d{1,4})\]$/u
const SEPARATOR_LINE = /^[ \t]*(?:-[ \t]*){6,}$/u
const LEADING_QUOTE = /^「([\s\S]{1,4000}?)」[ \t]*\r?\n[ \t]*(?:-[ \t]*){6,}[ \t]*(?:\r?\n|$)/u
const TRAILING_QUOTE = /(?:^|\r?\n)[ \t]*(?:-[ \t]*){6,}[ \t]*\r?\n「([\s\S]{1,4000}?)」[ \t]*$/u
const MONEY_AMOUNT = /^[¥￥$€]?\s*\d[\d,]*(?:\.\d+)?\s*(?:元)?$/u

function splitFields(value) {
  return String(value || '').split(/\s+·\s+/u).map((part) => part.trim()).filter(Boolean)
}

function quoteFrom(value) {
  const text = String(value || '').trim()
  const match = /^([^：:\n]{1,32})[：:]\s*([\s\S]*)$/u.exec(text)
  return match ? { type: 'quote', author: match[1].trim(), text: match[2].trim() } : { type: 'quote', author: '', text }
}

function cardFrom(kind, rest) {
  const parts = splitFields(rest)
  const block = { type: 'card', kind, label: CARD_LABELS[kind], title: parts[0] || '', summary: '', source: '' }
  if (parts.length >= 3) {
    block.summary = parts.slice(1, -1).join(' · ')
    block.source = parts[parts.length - 1]
  } else if (parts.length === 2) {
    block.summary = parts[1]
  }
  return block
}

function moneyFrom(kind, rest) {
  const parts = splitFields(rest)
  const block = { type: 'money', kind, label: MONEY_LABELS[kind], amount: '', summary: '', status: '' }
  if (parts.length && MONEY_AMOUNT.test(parts[0])) block.amount = parts.shift()
  if (parts.length >= 2) block.status = parts.pop()
  block.summary = parts.join(' · ')
  return block
}

function mediaFrom(kind, label) {
  return { type: 'media', kind, label: String(label || '').trim() || MEDIA_LABELS[kind] }
}

// Returns a block for a tagged line, or null when the line is ordinary text.
export function parseTaggedLine(line) {
  const text = String(line || '').trim()
  if (!text.startsWith('[')) return null
  const placeholder = PLACEHOLDER_LINE.exec(text)
  if (placeholder) {
    const kind = PLACEHOLDER_KINDS[placeholder[1]]
    const detail = placeholder[2].trim()
    return mediaFrom(kind, kind === 'file' || kind === 'sticker' ? (detail === 'asset' ? '' : detail) : '')
  }
  const opaque = OPAQUE_LINE.exec(text)
  if (opaque) {
    if (opaque[1] === 'reply' || opaque[2] === '7') return { type: 'quote', author: '', text: '' }
    return mediaFrom('unknown', OPAQUE_KIND_LABELS[opaque[1]] || OPAQUE_TYPE_LABELS[opaque[2]] || '暂不支持显示的消息')
  }
  const tagged = TAG_LINE.exec(text)
  if (!tagged) return null
  const tag = tagged[1].trim().toLowerCase()
  const rest = tagged[2].trim()
  if (CARD_TAGS.has(tag)) return cardFrom(CARD_TAGS.get(tag), rest)
  if (MONEY_TAGS.has(tag)) return moneyFrom(MONEY_TAGS.get(tag), rest)
  if (QUOTE_TAGS.has(tag)) return quoteFrom(rest)
  if (NOTICE_TAGS.has(tag)) return { type: 'notice', kind: 'pat', text: rest || '拍了拍' }
  if (MEDIA_TAGS.has(tag)) {
    const kind = MEDIA_TAGS.get(tag)
    if (kind === 'image' && rest) return null
    return mediaFrom(kind, rest)
  }
  return null
}

function splitWeChatQuote(body) {
  const leading = LEADING_QUOTE.exec(body)
  if (leading) return { quote: quoteFrom(leading[1]), rest: body.slice(leading[0].length), position: 'start' }
  const trailing = TRAILING_QUOTE.exec(body)
  if (trailing) return { quote: quoteFrom(trailing[1]), rest: body.slice(0, trailing.index), position: 'end' }
  return null
}

function pushText(blocks, lines) {
  while (lines.length && !lines[0].trim()) lines.shift()
  while (lines.length && !lines[lines.length - 1].trim()) lines.pop()
  if (lines.length) blocks.push({ type: 'text', text: lines.join('\n') })
}

export function parseMessageBody(value) {
  const body = String(value ?? '')
  const blocks = []
  const quoted = splitWeChatQuote(body)
  const source = quoted ? quoted.rest : body
  let pending = []
  for (const line of source.split(/\r?\n/u)) {
    const block = SEPARATOR_LINE.test(line) ? null : parseTaggedLine(line)
    if (!block) {
      pending.push(line)
      continue
    }
    pushText(blocks, pending)
    pending = []
    blocks.push(block)
  }
  pushText(blocks, pending)
  if (quoted) blocks.unshift(quoted.quote)
  return blocks
}

function previewLine(line) {
  const block = parseTaggedLine(line)
  if (!block) return line.trim()
  if (block.type === 'quote') return ''
  if (block.type === 'card') return `[${block.label}] ${block.title}`.trim()
  if (block.type === 'money') return `[${block.label}] ${block.amount || block.summary}`.trim()
  if (block.type === 'notice') return `[拍一拍] ${block.text}`
  return block.kind === 'unknown' || block.label === MEDIA_LABELS[block.kind]
    ? `[${block.label}]` : `[${MEDIA_LABELS[block.kind]}] ${block.label}`
}

// One-line summary for the conversation list. Group digests may carry a
// "发送者：" prefix before the tag, which is preserved.
export function previewText(value) {
  const body = String(value ?? '')
  const quoted = splitWeChatQuote(body)
  const lines = (quoted ? quoted.rest : body).split(/\r?\n/u)
  return lines.map((line) => {
    const prefixed = /^([^：:\n[\]]{1,24}[：:]\s?)(\[[\s\S]*)$/u.exec(line.trim())
    return prefixed ? `${prefixed[1]}${previewLine(prefixed[2])}` : previewLine(line)
  }).filter(Boolean).join(' ').trim()
}
