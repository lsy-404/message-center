// Labels for AI access rules and internal message marks. The Worker owns the
// rules; this module only names them for the inbox.

export const AGENT_ACCESS_KEYS = ['visible', 'push', 'commands', 'reply']
export const AGENT_CATEGORIES = ['direct', 'group', 'group_assistant']

export const MESSAGE_MARK_BITS = {
  sentByAgent: 1,
  sentByOwner: 2,
  readByOwner: 4,
  readByAgent: 8,
  noCommandAuthority: 16,
}

const MARK_DESCRIPTIONS = [
  [1, 'AI 发送'],
  [2, '人发送'],
  [4, '人已读'],
  [8, 'AI 已读'],
  [16, '发送人无指令权限'],
]

const CATEGORY_LABELS = { direct: '私聊', group: '群聊', group_assistant: '群助手中的群聊' }
const SOURCE_LABELS = { default: '默认', connector: '接入设置', conversation: '本会话' }

export function agentCategoryLabel(category) {
  return CATEGORY_LABELS[category] || CATEGORY_LABELS.direct
}

export function agentCategoryShortLabel(category) {
  return { direct: '私聊', group: '群聊', group_assistant: '群助手中' }[category] || '私聊'
}

export function agentSourceLabel(source) {
  return SOURCE_LABELS[source] || SOURCE_LABELS.default
}

export function agentKeyCopy(key, category = 'direct') {
  if (key === 'visible') return { label: 'AI 可见', description: 'AI 可以读取这个会话的消息' }
  if (key === 'push') {
    return category === 'direct'
      ? { label: '主动推送处理', description: '新消息进入 AI 待处理队列' }
      : { label: '@或关键词时推送', description: '只有@你或命中关键词的消息进入 AI 待处理队列' }
  }
  if (key === 'commands') return { label: '接受指令', description: '授权的发送人可以向 AI 下指令' }
  return { label: 'AI 可回复', description: 'AI 可以代你回复' }
}

export function agentColumnLabel(key) {
  return { visible: '可见', push: '推送', commands: '指令', reply: '回复' }[key] || key
}

// Short summary for the thread header, most significant first.
export function agentAccessSummary(access) {
  if (!access) return []
  if (!access.visible) return ['AI 不可见']
  return [
    access.push ? (access.category === 'direct' ? '主动处理' : '@时处理') : '不推送',
    access.reply ? '可回复' : '不回复',
    access.commands ? '接受指令' : '无指令',
  ]
}

// Returns new connector overrides with one switch set explicitly.
export function setConnectorOverride(settings, category, key, value) {
  const next = {}
  for (const name of AGENT_CATEGORIES) {
    if (settings?.[name] && Object.keys(settings[name]).length) next[name] = { ...settings[name] }
  }
  next[category] = { ...(next[category] || {}), [key]: Boolean(value) }
  return next
}

export function describeMarks(marks) {
  const value = Number(marks) || 0
  const parts = MARK_DESCRIPTIONS.filter(([bit]) => (value & bit) === bit).map(([bit, label]) => `${label}(${bit})`)
  return `内部标记 ${value}${parts.length ? `：${parts.join(' + ')}` : ''}`
}

// Tags shown under a message. Authorship is implied for its own read state:
// the owner has read what the owner sent, and the AI has read what it sent.
export function messageMarkTags(marks, options = {}) {
  const value = Number(marks) || 0
  const has = (bit) => (value & bit) === bit
  const tags = []
  if (has(MESSAGE_MARK_BITS.sentByAgent)) tags.push({ key: 'sent-agent', label: 'AI 发', tone: 'ai' })
  else if (has(MESSAGE_MARK_BITS.sentByOwner)) tags.push({ key: 'sent-owner', label: '人发', tone: 'owner' })
  if (!has(MESSAGE_MARK_BITS.sentByOwner)) {
    tags.push(has(MESSAGE_MARK_BITS.readByOwner)
      ? { key: 'owner-read', label: '人已读', tone: 'muted' }
      : { key: 'owner-unread', label: '人未读', tone: 'unread' })
  }
  if (!has(MESSAGE_MARK_BITS.sentByAgent)) {
    tags.push(has(MESSAGE_MARK_BITS.readByAgent)
      ? { key: 'agent-read', label: 'AI 已读', tone: 'muted' }
      : { key: 'agent-unread', label: 'AI 未读',
        tone: options.agentPushes && !has(MESSAGE_MARK_BITS.sentByOwner) ? 'unread' : 'muted' })
  }
  if (has(MESSAGE_MARK_BITS.noCommandAuthority) && options.commandsAccepted) {
    tags.push({ key: 'no-command', label: '无指令权限', tone: 'warning' })
  }
  return tags
}
