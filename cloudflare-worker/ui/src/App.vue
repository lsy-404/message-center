<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { FluentButton, FluentField, FluentSwitch, FluentTheme } from '@platform-kit/fluent/vue'
import AppIcon from './AppIcon.vue'
import type { IconName } from './icons'
import { createInboxReadGate, createInboxRefreshLoop } from './inbox-refresh.mjs'
import {
  clearPendingSendRequestKey,
  getPendingSendRequestKey,
  isAcceptedSendResponse,
} from './send-request-key.mjs'
import {
  CONVERSATION_PAGE_SIZE,
  conversationPageCount,
  filterConversations,
  normalizeChannelLabel,
  nextConversationPage,
  pageConversations,
  previousConversationPage,
} from './conversation-list.mjs'
import {
  avatarTone,
  buildThreadEntries,
  channelGlyph,
  channelTone,
  formatClock,
  formatFullStamp,
  formatListTime,
  formatRelativeAge,
} from './presentation.mjs'

type LayoutAcknowledgement = {
  enabled: boolean
  revision: number
  updatedAt?: string | null
  reason?: string | null
}

type LayoutControl = {
  enabled: boolean
  revision: number
  updatedAt?: string | null
  reason?: string | null
  deviceGeneration: number | null
  deviceActionId: string | null
  deviceActionRevision: number | null
  deviceActionEnabled: boolean | null
  acknowledgement: LayoutAcknowledgement | null
  synchronized: boolean
}

type Connector = {
  id: string
  kind: string
  channelLabel?: string | null
  accountLabel: string
  displayName: string
  mode: string
  state: string
  capabilities: string[]
  lastSeenAt?: string | null
  layoutControl?: LayoutControl
}

type Conversation = {
  id: string
  connectorId: string
  connectorKind: string
  connectorChannelLabel?: string | null
  conversationType?: string | null
  placement?: string | null
  pinned?: boolean
  title: string
  avatarLabel?: string | null
  avatarPath?: string | null
  unreadCount: number
  lastMessagePreview?: string | null
  lastMessageAt?: string | null
  connectorState: string
  capabilities: string[]
}

type ConversationListItem = Pick<Conversation,
  'id' | 'title' | 'avatarLabel' | 'avatarPath' | 'unreadCount' | 'lastMessagePreview' | 'lastMessageAt' | 'placement'
  | 'pinned' | 'conversationType'
> & { channel: string }

type Attachment = {
  id: string
  fileName: string
  mimeType?: string | null
  sizeBytes?: number | null
  downloadable?: boolean
}

type Message = {
  id: string
  direction: 'inbound' | 'outbound' | string
  senderName: string
  senderAvatarPath?: string | null
  body: string
  contentType: string
  occurredAt: string
  deliveryState?: string | null
  queueClass?: string | null
  authorRole?: 'contact' | 'owner' | 'agent' | string | null
  agentState?: string | null
  attachments: Attachment[]
}

type StatusInfo = { label: string, tone: 'muted' | 'success' | 'warning' | 'danger' | 'ai', icon: IconName }

type Snapshot = {
  connectors: Connector[]
  conversations: Conversation[]
  messages: Message[]
  selectedConversationId: string | null
}

type StagedAttachment = Attachment & { sha256?: string }
type AvatarRetryState = {
  revision: number
  failures: number
  retryAt: number
  phase: 'failed' | 'loading' | 'loaded'
}

type MessageScrollState = {
  nearBottom: boolean
  scrollTop: number
  anchorMessageId: string | null
  anchorOffset: number
}

const emptySnapshot = (): Snapshot => ({ connectors: [], conversations: [], messages: [], selectedConversationId: null })
const snapshot = ref<Snapshot>(emptySnapshot())
const selectedId = ref('')
const activeFilter = ref('all')
const activeConnectorId = ref('')
const conversationSearch = ref('')
const unreadOnly = ref(false)
const manualRefreshing = ref(false)
const nowTick = ref(Date.now())
const conversationPage = ref(0)
const conversationListElement = ref<HTMLElement | null>(null)
const showInstances = ref(false)
const mobileThread = ref(false)
const loading = ref(true)
const detailLoading = ref(false)
const draft = ref('')
const staged = ref<StagedAttachment[]>([])
const toast = ref('')
const inboxReads = createInboxReadGate()
let inboxTimeout: number | undefined
let refreshLoop: ReturnType<typeof createInboxRefreshLoop> | undefined
let toastTimer: number | undefined
let clockTimer: number | undefined
let pendingScrollToBottomId: string | null = null
const draftCache = new Map<string, string>()
const stagedCache = new Map<string, StagedAttachment[]>()
const sendingConversationIds = ref(new Set<string>())
const uploadingConversationIds = ref(new Set<string>())
const updatingLayoutConnectorIds = ref(new Set<string>())
const avatarRetryStates = ref(new Map<string, AvatarRetryState>())
const loadedAttachmentImages = ref(new Set<string>())
const AVATAR_RETRY_BASE_MS = 5_000
const AVATAR_RETRY_MAX_MS = 60_000

const selectedConversation = computed(() =>
  snapshot.value.conversations.find((item) => item.id === selectedId.value) ?? null,
)
const selectedConversationConnector = computed(() =>
  snapshot.value.connectors.find((item) => item.id === selectedConversation.value?.connectorId) ?? null,
)
const filters = computed(() => {
  const labels = new Map<string, string>()
  for (const conversation of snapshot.value.conversations) {
    const label = channelLabel(conversation)
    labels.set(label, label)
  }
  const summarize = (items: Conversation[]) => ({
    count: items.length,
    unread: items.reduce((total, item) => total + Math.max(0, Number(item.unreadCount) || 0), 0),
  })
  return [
    { id: 'all', label: '全部', channel: '', ...summarize(snapshot.value.conversations) },
    ...[...labels.values()].map((label) => ({
      id: `channel:${label}`,
      label,
      channel: label,
      ...summarize(snapshot.value.conversations.filter((item) => channelLabel(item) === label)),
    })),
  ]
})
const totalUnread = computed(() => filters.value[0]?.unread ?? 0)
const onlineConnectorCount = computed(() => snapshot.value.connectors.filter((item) => item.state === 'online').length)
const activeFilterLabel = computed(() => {
  if (activeConnectorId.value) {
    const connector = snapshot.value.connectors.find((item) => item.id === activeConnectorId.value)
    if (connector) return connector.accountLabel
  }
  return activeFilter.value === 'all' ? '收件箱' : activeFilter.value.slice('channel:'.length)
})
const filteredUnread = computed(() => filteredConversations.value
  .reduce((total, item) => total + Math.max(0, Number(item.unreadCount) || 0), 0))

const filteredConversations = computed(() => filterConversations(snapshot.value.conversations, {
  connectorId: activeConnectorId.value,
  channelLabel: activeFilter.value === 'all' ? '' : activeFilter.value.slice('channel:'.length),
  query: conversationSearch.value,
  unreadOnly: unreadOnly.value,
  getChannelLabel: channelLabel,
}))
const visibleConversations = computed(() => pageConversations(
  filteredConversations.value,
  conversationPage.value,
  CONVERSATION_PAGE_SIZE,
))
const totalConversationPages = computed(() => conversationPageCount(filteredConversations.value.length))
const conversationRangeStart = computed(() => filteredConversations.value.length
  ? conversationPage.value * CONVERSATION_PAGE_SIZE + 1 : 0)
const conversationRangeEnd = computed(() => Math.min(
  (conversationPage.value + 1) * CONVERSATION_PAGE_SIZE,
  filteredConversations.value.length,
))
const conversationRows = computed<ConversationListItem[]>(() => visibleConversations.value.map((conversation) => ({
  id: conversation.id,
  title: conversation.title,
  avatarLabel: conversation.avatarLabel,
  avatarPath: conversation.avatarPath,
  unreadCount: conversation.unreadCount,
  lastMessagePreview: conversation.lastMessagePreview,
  lastMessageAt: conversation.lastMessageAt,
  placement: conversation.placement,
  pinned: conversation.pinned,
  conversationType: conversation.conversationType,
  channel: channelLabel(conversation),
})))

watch([activeFilter, activeConnectorId, conversationSearch, unreadOnly], async () => {
  conversationPage.value = 0
  await nextTick()
  conversationListElement.value?.scrollTo(0, 0)
})

const threadEntries = computed(() => buildThreadEntries(snapshot.value.messages, nowTick.value))
const threadAgentSummary = computed(() => {
  const summary = { working: 0, waiting: 0, escalated: 0 }
  for (const message of snapshot.value.messages) {
    if (message.direction === 'outbound') continue
    if (message.agentState === 'leased') summary.working += 1
    else if (message.agentState === 'pending') summary.waiting += 1
    else if (message.agentState === 'dead_letter') summary.escalated += 1
  }
  return summary
})

const threadRows = computed(() => threadEntries.value.map((entry) => entry.kind === 'day' ? entry : {
  ...entry,
  byAgent: isAgentMessage(entry.message),
  delivery: deliveryStateInfo(entry.message),
  agent: agentStateInfo(entry.message),
}))

const hasKnownConversationActivity = computed(() => Boolean(
  selectedConversation.value?.lastMessageAt || selectedConversation.value?.lastMessagePreview?.trim(),
))

const canSendText = computed(() => selectedConversation.value?.capabilities.includes('send_text') ?? false)
const deviceConversation = computed(() => selectedConversationConnector.value?.mode === 'device_relay')
const maxTextLength = computed(() => deviceConversation.value ? 500 : 20_000)
const canSendFiles = computed(() => {
  if (selectedConversationConnector.value?.mode === 'device_relay'
      && selectedConversation.value?.conversationType !== 'group') return false
  const capabilities = selectedConversation.value?.capabilities ?? []
  return capabilities.includes('send_files') || capabilities.includes('send_images') || capabilities.includes('send_video')
})
const fileAccept = computed(() => {
  const capabilities = selectedConversation.value?.capabilities ?? []
  if (capabilities.includes('send_files')) return undefined
  return [
    ...(capabilities.includes('send_images') ? ['image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/heic'] : []),
    ...(capabilities.includes('send_video')
      ? ['video/mp4', 'video/quicktime', 'video/webm', 'video/x-msvideo', 'video/x-matroska']
      : []),
  ].join(',') || undefined
})
const canSend = computed(() => {
  const hasText = Boolean(draft.value.trim())
  const hasFiles = staged.value.length > 0
  return Boolean(selectedConversation.value)
    && !sendingConversationIds.value.has(selectedId.value)
    && !uploadingConversationIds.value.has(selectedId.value)
    && (hasText || hasFiles)
    && (!deviceConversation.value || !(hasText && hasFiles))
    && (!deviceConversation.value || staged.value.length <= 1)
    && (!hasText || (canSendText.value && draft.value.length <= maxTextLength.value))
    && (!hasFiles || (canSendFiles.value
      && staged.value.every((file) => supportsAttachment(
        selectedConversation.value?.capabilities ?? [], file.mimeType, file.fileName,
      ))))
})

function channelLabel(item: Connector | Conversation | null | undefined) {
  if (!item) return '未知'
  if ('channelLabel' in item && item.channelLabel) return normalizeChannelLabel(item.channelLabel)
  if ('connectorChannelLabel' in item && item.connectorChannelLabel) {
    return normalizeChannelLabel(item.connectorChannelLabel)
  }
  const kind = 'kind' in item ? item.kind : item.connectorKind
  return normalizeChannelLabel(
    ({ im: '即时消息', email: '邮箱', sms: '短信', voice: '语音', webhook: 'Webhook' } as Record<string, string>)[kind] || kind,
  )
}

function capLabel(capability: string) {
  return ({
    receive_text: '收文字', send_text: '发文字', receive_files: '收附件', send_files: '发附件',
    receive_images: '收图片', send_images: '发图片', receive_video: '收视频', send_video: '发视频',
    threads: '会话串', reactions: '回应', layout_control: '布局控制',
  } as Record<string, string>)[capability] || capability
}

function capabilityGroups(capabilities: string[]) {
  return [
    { id: 'receive', label: '接收', items: capabilities.filter((item) => item.startsWith('receive_')) },
    { id: 'send', label: '发送', items: capabilities.filter((item) => item.startsWith('send_')) },
    {
      id: 'other',
      label: '其他',
      items: capabilities.filter((item) => !item.startsWith('receive_') && !item.startsWith('send_')),
    },
  ].filter((group) => group.items.length)
}

function modeLabel(mode: string) {
  return ({ device_relay: '设备中继', cloud_relay: '云端中继', webhook: 'Webhook' } as Record<string, string>)[mode] || mode
}

function supportsAttachment(capabilities: string[], mimeType?: string | null, fileName = '') {
  if (capabilities.includes('send_files')) return true
  const mime = String(mimeType || '').toLowerCase()
  const extension = fileName.includes('.') ? fileName.split('.').at(-1)?.toLowerCase() || '' : ''
  const image = ['image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/heic'].includes(mime)
    || (!mime && ['png', 'jpg', 'jpeg', 'gif', 'webp', 'heic'].includes(extension))
  const video = ['video/mp4', 'video/quicktime', 'video/webm', 'video/x-msvideo', 'video/x-matroska'].includes(mime)
    || (!mime && ['mp4', 'mov', 'm4v', 'webm', 'avi', 'mkv'].includes(extension))
  return (image && capabilities.includes('send_images')) || (video && capabilities.includes('send_video'))
}

function initials(value?: string | null) {
  const text = String(value || '?').trim()
  const words = text.split(/\s+/).filter(Boolean)
  if (words.length > 1 && /^[\x21-\x7e]+$/.test(words.join(''))) {
    return words.slice(0, 2).map((word) => word[0]).join('').toUpperCase()
  }
  return [...text].slice(0, 2).join('') || '?'
}

function statusLabel(state?: string | null) {
  return state === 'online' ? '在线' : '离线'
}

function deliveryStateInfo(message: Message): StatusInfo | null {
  if (message.direction !== 'outbound') return null
  return ({
    queued: { label: '等待发送', tone: 'muted', icon: 'clock' },
    delivered: { label: '已发送', tone: 'success', icon: 'check' },
    failed: { label: '发送失败', tone: 'danger', icon: 'error' },
    uncertain: { label: '待确认（不可自动重发）', tone: 'warning', icon: 'warning' },
  } as Record<string, StatusInfo>)[message.deliveryState || ''] || null
}

function agentStateInfo(message: Message): StatusInfo | null {
  if (message.direction === 'outbound') return null
  return ({
    pending: { label: '等待 AI 处理', tone: 'muted', icon: 'hourglass' },
    leased: { label: 'AI 处理中', tone: 'ai', icon: 'bot' },
    completed: { label: 'AI 已处理', tone: 'muted', icon: 'checkCircle' },
    dead_letter: { label: '需人工处理', tone: 'warning', icon: 'personAlert' },
  } as Record<string, StatusInfo>)[message.agentState || ''] || null
}

function isAgentMessage(message: Message) {
  return message.direction === 'outbound' && message.authorRole === 'agent'
}

function senderLabel(message: Message) {
  return isAgentMessage(message) ? 'AI 代理' : message.senderName
}

function listTime(value?: string | null) {
  return formatListTime(value, nowTick.value)
}

function relativeAge(value?: string | null) {
  return formatRelativeAge(value, nowTick.value)
}

function isoTime(value?: string | null) {
  if (!value) return undefined
  const date = new Date(value)
  return Number.isNaN(date.valueOf()) ? undefined : date.toISOString()
}

function isFolded(conversation: Pick<Conversation, 'placement'>) {
  return conversation.placement === 'folded' || conversation.placement === 'message_box'
}

function conversationStateText(conversation: ConversationListItem) {
  return [
    conversation.pinned ? '置顶' : '',
    conversation.conversationType === 'group' ? '群聊' : '',
    conversation.placement === 'message_box' ? '消息盒子' : conversation.placement === 'folded' ? '折叠聊天' : '',
    conversation.unreadCount ? `${conversation.unreadCount} 条未读` : '',
  ].filter(Boolean).join('，')
}

function conversationPreview(conversation: ConversationListItem) {
  const preview = String(conversation.lastMessagePreview || '').trim()
  if (preview) return preview
  return conversation.lastMessageAt ? '最近消息尚未同步' : '暂无消息'
}

function captureMessageScroll(thread: HTMLElement): MessageScrollState {
  const bounds = thread.getBoundingClientRect()
  const anchor = [...thread.querySelectorAll<HTMLElement>('.message-row')]
    .find((row) => row.getBoundingClientRect().bottom > bounds.top + 1)
  return {
    nearBottom: thread.scrollHeight - thread.scrollTop - thread.clientHeight < 80,
    scrollTop: thread.scrollTop,
    anchorMessageId: anchor?.dataset.messageId || null,
    anchorOffset: anchor ? anchor.getBoundingClientRect().top - bounds.top : 0,
  }
}

function restoreMessageScroll(thread: HTMLElement, state: MessageScrollState | null) {
  if (!state) return
  const anchor = state.anchorMessageId
    ? [...thread.querySelectorAll<HTMLElement>('.message-row')]
      .find((row) => row.dataset.messageId === state.anchorMessageId)
    : null
  if (anchor) {
    const nextOffset = anchor.getBoundingClientRect().top - thread.getBoundingClientRect().top
    thread.scrollTop += nextOffset - state.anchorOffset
    return
  }
  thread.scrollTop = Math.min(state.scrollTop, Math.max(0, thread.scrollHeight - thread.clientHeight))
}

function formatBytes(value?: number | null) {
  const bytes = Number(value || 0)
  if (!bytes) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MiB`
}

function isImage(file: Attachment) {
  return Boolean(file.downloadable && file.mimeType?.startsWith('image/'))
}

function isVideo(file: Attachment) {
  return Boolean(file.downloadable && file.mimeType?.startsWith('video/'))
}

function messageBody(message: Message) {
  let loadedCount = message.attachments.filter((file) =>
    isImage(file) && loadedAttachmentImages.value.has(`${message.id}:${file.id}`),
  ).length
  if (!loadedCount) return message.body || ''
  return (message.body || '').split(/\r?\n/).filter((line) => {
    if (loadedCount > 0 && /^[ \t]*\[图片\][ \t]*$/.test(line)) {
      loadedCount -= 1
      return false
    }
    return true
  }).join('\n')
}

function setAttachmentImageLoaded(message: Message, file: Attachment, loaded: boolean) {
  const key = `${message.id}:${file.id}`
  const currentlyLoaded = loadedAttachmentImages.value.has(key)
  if (currentlyLoaded === loaded) return
  const next = new Set(loadedAttachmentImages.value)
  if (loaded) next.add(key)
  else next.delete(key)
  loadedAttachmentImages.value = next
}

function filePath(file: Attachment) {
  return `/api/files/${encodeURIComponent(file.id)}`
}

function avatarRevision(path?: string | null) {
  return path ? avatarRetryStates.value.get(path)?.revision ?? 0 : 0
}

function avatarSource(path?: string | null) {
  if (!path) return ''
  const revision = avatarRevision(path)
  if (!revision) return path
  const hashIndex = path.indexOf('#')
  const base = hashIndex >= 0 ? path.slice(0, hashIndex) : path
  const hash = hashIndex >= 0 ? path.slice(hashIndex) : ''
  return `${base}${base.includes('?') ? '&' : '?'}avatar-retry=${revision}${hash}`
}

function avatarKey(path?: string | null) {
  return `${path || ''}:${avatarRevision(path)}`
}

function retryDelay(failures: number) {
  return Math.min(AVATAR_RETRY_MAX_MS, AVATAR_RETRY_BASE_MS * (2 ** Math.min(Math.max(failures - 1, 0), 4)))
}

function imageFailed(event: Event) {
  const image = event.currentTarget as HTMLImageElement
  image.classList.add('is-broken')
  const path = image.dataset.avatarPath
  if (!path) return
  const revision = Number(image.dataset.avatarRevision || 0)
  const current = avatarRetryStates.value.get(path)
  if ((current?.revision ?? 0) !== revision || current?.phase === 'failed' || current?.phase === 'loaded') return
  const failures = (current?.failures ?? 0) + 1
  const next = new Map(avatarRetryStates.value)
  next.set(path, {
    revision,
    failures,
    retryAt: Date.now() + retryDelay(failures),
    phase: 'failed',
  })
  avatarRetryStates.value = next
}

function imageLoaded(event: Event) {
  const image = event.currentTarget as HTMLImageElement
  image.classList.remove('is-broken')
  const path = image.dataset.avatarPath
  if (!path) return
  const revision = Number(image.dataset.avatarRevision || 0)
  const current = avatarRetryStates.value.get(path)
  if (!current || current.revision !== revision || current.phase === 'loaded') return
  const next = new Map(avatarRetryStates.value)
  next.set(path, { revision, failures: 0, retryAt: 0, phase: 'loaded' })
  avatarRetryStates.value = next
}

function advanceAvatarRetries(conversations: Conversation[], messages: Message[]) {
  const activePaths = new Set([
    ...conversations.map((item) => item.avatarPath),
    ...messages.map((item) => item.senderAvatarPath),
  ].filter((path): path is string => Boolean(path)))
  const now = Date.now()
  const next = new Map(avatarRetryStates.value)
  let changed = false
  for (const [path, state] of next) {
    if (!activePaths.has(path)) {
      next.delete(path)
      changed = true
    } else if (state.phase === 'failed' && state.retryAt <= now) {
      next.set(path, {
        ...state,
        revision: Math.max(now, state.revision + 1),
        phase: 'loading',
      })
      changed = true
    }
  }
  if (changed) avatarRetryStates.value = next
}

function storeComposer() {
  if (!selectedId.value) return
  if (draft.value) draftCache.set(selectedId.value, draft.value)
  else draftCache.delete(selectedId.value)
  if (staged.value.length) stagedCache.set(selectedId.value, [...staged.value])
  else stagedCache.delete(selectedId.value)
}

function restoreComposer(conversationId: string) {
  draft.value = draftCache.get(conversationId) || ''
  staged.value = [...(stagedCache.get(conversationId) || [])]
}

function notify(message: string) {
  toast.value = message
  if (toastTimer) window.clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => { toast.value = '' }, 3000)
}

async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { cache: 'no-store', credentials: 'same-origin', ...options })
  const type = response.headers.get('content-type') || ''
  const body = type.includes('json') ? await response.json() : null
  if (response.status === 401) {
    window.location.replace('/login')
    throw new Error('access_required')
  }
  if (!response.ok) throw new Error(body?.error || `HTTP ${response.status}`)
  return body as T
}

function sameInbox(left: Snapshot, right: Snapshot) {
  if (left.selectedConversationId !== right.selectedConversationId) return false
  if (left.connectors.length !== right.connectors.length
      || left.conversations.length !== right.conversations.length
      || left.messages.length !== right.messages.length) return false
  for (let index = 0; index < left.connectors.length; index += 1) {
    const a = left.connectors[index]
    const b = right.connectors[index]
    if (a.id !== b.id || a.accountLabel !== b.accountLabel || a.displayName !== b.displayName
        || a.channelLabel !== b.channelLabel || a.mode !== b.mode || a.state !== b.state
        || a.lastSeenAt !== b.lastSeenAt || a.layoutControl?.enabled !== b.layoutControl?.enabled
        || a.layoutControl?.revision !== b.layoutControl?.revision
        || a.layoutControl?.updatedAt !== b.layoutControl?.updatedAt || a.layoutControl?.reason !== b.layoutControl?.reason
        || a.layoutControl?.deviceGeneration !== b.layoutControl?.deviceGeneration
        || a.layoutControl?.deviceActionId !== b.layoutControl?.deviceActionId
        || a.layoutControl?.deviceActionRevision !== b.layoutControl?.deviceActionRevision
        || a.layoutControl?.deviceActionEnabled !== b.layoutControl?.deviceActionEnabled
        || a.layoutControl?.acknowledgement?.revision !== b.layoutControl?.acknowledgement?.revision
        || a.layoutControl?.acknowledgement?.updatedAt !== b.layoutControl?.acknowledgement?.updatedAt
        || a.layoutControl?.synchronized !== b.layoutControl?.synchronized
        || a.capabilities.length !== b.capabilities.length
        || a.capabilities.some((value, itemIndex) => value !== b.capabilities[itemIndex])) return false
  }
  for (let index = 0; index < left.conversations.length; index += 1) {
    const a = left.conversations[index]
    const b = right.conversations[index]
    if (a.id !== b.id || a.title !== b.title || a.avatarPath !== b.avatarPath
        || a.avatarLabel !== b.avatarLabel || a.connectorId !== b.connectorId
        || a.connectorKind !== b.connectorKind || a.connectorChannelLabel !== b.connectorChannelLabel
        || a.conversationType !== b.conversationType
        || a.unreadCount !== b.unreadCount || a.lastMessagePreview !== b.lastMessagePreview
        || a.lastMessageAt !== b.lastMessageAt || a.placement !== b.placement
        || a.pinned !== b.pinned || a.connectorState !== b.connectorState
        || a.capabilities.length !== b.capabilities.length
        || a.capabilities.some((value, itemIndex) => value !== b.capabilities[itemIndex])) return false
  }
  for (let index = 0; index < left.messages.length; index += 1) {
    const a = left.messages[index]
    const b = right.messages[index]
    if (a.id !== b.id || a.direction !== b.direction || a.senderName !== b.senderName
        || a.senderAvatarPath !== b.senderAvatarPath
        || a.body !== b.body || a.contentType !== b.contentType || a.occurredAt !== b.occurredAt
        || a.deliveryState !== b.deliveryState || a.queueClass !== b.queueClass
        || a.authorRole !== b.authorRole || a.agentState !== b.agentState
        || a.attachments.length !== b.attachments.length) return false
    for (let attachmentIndex = 0; attachmentIndex < a.attachments.length; attachmentIndex += 1) {
      const file = a.attachments[attachmentIndex]
      const nextFile = b.attachments[attachmentIndex]
      if (file.id !== nextFile.id || file.fileName !== nextFile.fileName
          || file.mimeType !== nextFile.mimeType || file.sizeBytes !== nextFile.sizeBytes
          || file.downloadable !== nextFile.downloadable) return false
    }
  }
  return true
}

function cancelInboxRead() {
  if (inboxTimeout !== undefined) window.clearTimeout(inboxTimeout)
  inboxTimeout = undefined
  inboxReads.cancel()
}

async function load(conversationId = selectedId.value, silent = false, forceScrollToBottom = false) {
  if (document.hidden || !navigator.onLine) {
    if (!silent) detailLoading.value = false
    loading.value = false
    return
  }
  cancelInboxRead()
  const request = inboxReads.begin(conversationId)
  let timedOut = false
  inboxTimeout = window.setTimeout(() => {
    timedOut = true
    request.controller.abort()
  }, 20_000)
  if (!silent) detailLoading.value = Boolean(conversationId)
  const query = new URLSearchParams({ refresh: String(Date.now()) })
  if (conversationId) query.set('conversationId', conversationId)
  try {
    const body = await api<Snapshot & { ok: boolean }>(`/api/inbox?${query}`, { signal: request.controller.signal })
    if (!inboxReads.isCurrent(request, selectedId.value)) return
    const priorThread = document.querySelector<HTMLElement>('.message-scroll')
    const priorSelectedId = selectedId.value
    const scrollState = priorThread ? captureMessageScroll(priorThread) : null
    const nextSelectedId = body.selectedConversationId || ''
    const selectionChanged = nextSelectedId !== priorSelectedId
    if (selectionChanged) {
      storeComposer()
      selectedId.value = nextSelectedId
      restoreComposer(nextSelectedId)
    }
    const currentImageKeys = new Set(body.messages.flatMap((message) =>
      message.attachments.filter(isImage).map((file) => `${message.id}:${file.id}`),
    ))
    if ([...loadedAttachmentImages.value].some((key) => !currentImageKeys.has(key))) {
      loadedAttachmentImages.value = new Set([...loadedAttachmentImages.value].filter((key) => currentImageKeys.has(key)))
    }
    advanceAvatarRetries(body.conversations, body.messages)
    body.connectors = mergeConnectorLayoutControls(body.connectors)
    if (sameInbox(snapshot.value, body)) return
    snapshot.value = body
    await nextTick()
    if (!inboxReads.isActive(request)) return
    const thread = document.querySelector<HTMLElement>('.message-scroll')
    const shouldForceScroll = forceScrollToBottom || pendingScrollToBottomId === nextSelectedId
    if (thread) {
      if (!silent || selectionChanged || shouldForceScroll || scrollState?.nearBottom !== false) {
        thread.scrollTop = thread.scrollHeight
      } else {
        restoreMessageScroll(thread, scrollState)
      }
    }
    if (shouldForceScroll && pendingScrollToBottomId === nextSelectedId) pendingScrollToBottomId = null
  } catch (error) {
    if (timedOut) throw new Error('加载超时，请稍后重试')
    throw error
  } finally {
    const ownsRequest = inboxReads.isCurrent(request, request.conversationId)
    if (ownsRequest) {
      if (inboxTimeout !== undefined) window.clearTimeout(inboxTimeout)
      inboxTimeout = undefined
      inboxReads.finish(request)
    }
    if (ownsRequest) {
      loading.value = false
      detailLoading.value = false
    }
  }
}

async function selectConversation(conversation: Conversation, openMobileThread = true) {
  cancelInboxRead()
  storeComposer()
  if (conversation.id !== selectedId.value) pendingScrollToBottomId = null
  selectedId.value = conversation.id
  restoreComposer(conversation.id)
  mobileThread.value = openMobileThread
  showInstances.value = false
  loadedAttachmentImages.value = new Set()
  detailLoading.value = true
  snapshot.value.messages = []
  try {
    await load(conversation.id)
  } catch (error) {
    if (selectedId.value === conversation.id && !(error instanceof DOMException && error.name === 'AbortError')) {
      notify(`详情加载失败：${error instanceof Error ? error.message : String(error)}`)
    }
  }
}

async function refreshNow() {
  if (manualRefreshing.value) return
  manualRefreshing.value = true
  try {
    await load(selectedId.value)
  } catch (error) {
    if (!(error instanceof DOMException && error.name === 'AbortError')) {
      notify(`刷新失败：${error instanceof Error ? error.message : String(error)}`)
    }
  } finally {
    manualRefreshing.value = false
  }
}

function showNextConversationPage() {
  conversationPage.value = nextConversationPage(conversationPage.value, filteredConversations.value.length)
}

function showPreviousConversationPage() {
  conversationPage.value = previousConversationPage(conversationPage.value)
}

function selectConversationById(conversationId: string) {
  const conversation = snapshot.value.conversations.find((item) => item.id === conversationId)
  if (conversation) void selectConversation(conversation)
}

function selectFilter(id: string, connectorId = '') {
  activeFilter.value = id
  activeConnectorId.value = connectorId
  showInstances.value = false
  mobileThread.value = false
  if (!filteredConversations.value.some((conversation) => conversation.id === selectedId.value)) {
    const nextConversation = filteredConversations.value[0]
    if (nextConversation) {
      void selectConversation(nextConversation, false)
    } else {
      storeComposer()
      pendingScrollToBottomId = null
      cancelInboxRead()
      selectedId.value = ''
      restoreComposer('')
      snapshot.value.messages = []
      detailLoading.value = false
    }
  }
}

function showConnectorManagement() {
  showInstances.value = true
  mobileThread.value = false
}

function connectorLayoutControl(connector: Connector): LayoutControl {
  return connector.layoutControl ?? {
    enabled: false,
    revision: 0,
    updatedAt: null,
    reason: 'not_configured',
    deviceGeneration: null,
    deviceActionId: null,
    deviceActionRevision: null,
    deviceActionEnabled: null,
    acknowledgement: null,
    synchronized: false,
  }
}

function supportsLayoutAutoRecovery(connector: Connector) {
  return connector.mode === 'device_relay' && connector.capabilities.includes('layout_control')
}

function mergeConnectorLayoutControls(connectors: Connector[]) {
  const previousById = new Map(snapshot.value.connectors.map((connector) => [connector.id, connector]))
  return connectors.map((connector) => {
    const incoming = connector.layoutControl
    const previous = previousById.get(connector.id)?.layoutControl
    if (!supportsLayoutAutoRecovery(connector) || !incoming || !previous) return connector
    if (incoming.revision < previous.revision) return { ...connector, layoutControl: previous }
    if (incoming.revision > previous.revision) return connector
    const incomingAcknowledgement = incoming.acknowledgement
    const previousAcknowledgement = previous.acknowledgement
    const incomingAcknowledgementRevision = incomingAcknowledgement?.revision ?? -1
    const previousAcknowledgementRevision = previousAcknowledgement?.revision ?? -1
    const incomingAcknowledgedAt = Date.parse(incomingAcknowledgement?.updatedAt || '') || 0
    const previousAcknowledgedAt = Date.parse(previousAcknowledgement?.updatedAt || '') || 0
    if (previousAcknowledgementRevision > incomingAcknowledgementRevision ||
        (previousAcknowledgementRevision === incomingAcknowledgementRevision &&
          previousAcknowledgedAt > incomingAcknowledgedAt)) {
      const acknowledgement = previousAcknowledgement
      return {
        ...connector,
        layoutControl: {
          ...incoming,
          acknowledgement,
          synchronized: Boolean(acknowledgement && acknowledgement.revision === incoming.revision &&
            acknowledgement.enabled === incoming.enabled),
        },
      }
    }
    return connector
  })
}

function layoutControlStatus(connector: Connector) {
  if (updatingLayoutConnectorIds.value.has(connector.id)) return '正在更新'
  const state = connectorLayoutControl(connector)
  if (state.enabled) return state.synchronized ? '已在设备启用' : '等待设备启用'
  if (!state.acknowledgement && state.revision === 0) return '尚未启用'
  return state.synchronized ? '已在设备关闭' : '等待设备停止'
}

async function setLayoutAutoRecovery(connector: Connector, enabled: boolean) {
  if (updatingLayoutConnectorIds.value.has(connector.id)) return
  const expectedRevision = connectorLayoutControl(connector).revision
  updatingLayoutConnectorIds.value = new Set([...updatingLayoutConnectorIds.value, connector.id])
  try {
    const result = await api<{ layoutControl: LayoutControl }>(
      `/api/connectors/${encodeURIComponent(connector.id)}/layout-control`,
      {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ enabled, expectedRevision }),
      },
    )
    const current = snapshot.value.connectors.find((item) => item.id === connector.id)
    if (current) current.layoutControl = result.layoutControl
    notify(enabled ? '已请求启用自动恢复布局' : '已请求关闭自动恢复布局')
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    if (message === 'layout_revision_conflict') {
      notify('布局控制状态已更新，正在重新载入')
      await load(selectedId.value, true).catch(() => {})
    } else {
      notify(`布局控制失败：${message}`)
    }
  } finally {
    const remaining = new Set(updatingLayoutConnectorIds.value)
    remaining.delete(connector.id)
    updatingLayoutConnectorIds.value = remaining
  }
}

async function uploadFiles(event: Event) {
  const input = event.currentTarget as HTMLInputElement
  const targetConversationId = selectedId.value
  const targetCapabilities = [...(selectedConversation.value?.capabilities ?? [])]
  const targetDeviceConversation = selectedConversationConnector.value?.mode === 'device_relay'
  if (!targetConversationId) return
  const selectedFiles = Array.from(input.files || [])
  if (targetDeviceConversation && staged.value.length + selectedFiles.length > 1) {
    notify('设备接入请每次单独发送一个附件')
    input.value = ''
    return
  }
  uploadingConversationIds.value = new Set([...uploadingConversationIds.value, targetConversationId])
  try {
    for (const file of selectedFiles) {
      if (targetDeviceConversation && (file.size > 10 * 1024 * 1024 || file.name.length > 120
          || /[\\/:*?"<>|\u0000-\u001f]/.test(file.name))) {
        notify(`附件不符合设备接入限制：${file.name}`)
        continue
      }
      if (!supportsAttachment(targetCapabilities, file.type, file.name)) {
        notify(`此接入不支持发送 ${file.name}`)
        continue
      }
      const form = new FormData()
      form.append('file', file)
      try {
        const result = await api<{ attachment: StagedAttachment }>('/api/files', { method: 'POST', body: form })
        if (!supportsAttachment(targetCapabilities, result.attachment.mimeType, result.attachment.fileName)) {
          await api(`/api/files/${encodeURIComponent(result.attachment.id)}`, { method: 'DELETE' })
          notify(`无法验证 ${file.name} 的媒体格式`)
          continue
        }
        if (selectedId.value === targetConversationId) {
          staged.value.push(result.attachment)
        } else {
          const values = stagedCache.get(targetConversationId) || []
          stagedCache.set(targetConversationId, [...values, result.attachment])
        }
        notify(`已添加 ${file.name}`)
      } catch (error) {
        notify(`附件失败：${error instanceof Error ? error.message : String(error)}`)
      }
    }
  } finally {
    const remaining = new Set(uploadingConversationIds.value)
    remaining.delete(targetConversationId)
    uploadingConversationIds.value = remaining
    input.value = ''
  }
}

async function removeStaged(index: number) {
  const [removed] = staged.value.splice(index, 1)
  if (!removed) return
  try {
    await api(`/api/files/${encodeURIComponent(removed.id)}`, { method: 'DELETE' })
  } catch (error) {
    notify(`附件清理失败：${error instanceof Error ? error.message : String(error)}`)
  }
}

async function send() {
  const conversation = selectedConversation.value
  if (!conversation || !canSend.value || sendingConversationIds.value.has(conversation.id)) return
  const targetConversationId = conversation.id
  const sentDraft = draft.value
  const sentFiles = [...staged.value]
  sendingConversationIds.value = new Set([...sendingConversationIds.value, targetConversationId])
  try {
    const pendingRequest = await getPendingSendRequestKey(
      targetConversationId, sentDraft, sentFiles.map((file) => file.id),
    )
    const accepted = await api<{
      ok: boolean
      messageId?: string
      commandId?: string
    }>('/api/messages/send', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        conversationId: conversation.id,
        body: sentDraft,
        attachmentIds: sentFiles.map((file) => file.id),
        clientRequestId: pendingRequest.clientRequestId,
      }),
    })
    if (!isAcceptedSendResponse(accepted)) throw new Error('send_acceptance_unconfirmed')
    try {
      clearPendingSendRequestKey(pendingRequest.fingerprint, pendingRequest.clientRequestId)
    } catch {
      // The accepted command remains recoverable with this request key.
    }
  } catch (error) {
    notify(`发送失败：${error instanceof Error ? error.message : String(error)}`)
    return
  } finally {
    const remaining = new Set(sendingConversationIds.value)
    remaining.delete(targetConversationId)
    sendingConversationIds.value = remaining
  }
  if (draftCache.get(targetConversationId) === sentDraft) draftCache.delete(targetConversationId)
  const sentFileIds = new Set(sentFiles.map((file) => file.id))
  const cachedFiles = stagedCache.get(targetConversationId)
  if (cachedFiles) {
    const remaining = cachedFiles.filter((file) => !sentFileIds.has(file.id))
    if (remaining.length) stagedCache.set(targetConversationId, remaining)
    else stagedCache.delete(targetConversationId)
  }
  if (selectedId.value === targetConversationId) {
    if (draft.value === sentDraft) draft.value = ''
    staged.value = staged.value.filter((file) => !sentFileIds.has(file.id))
  }
  notify('已加入发送队列')
  if (selectedId.value === targetConversationId) pendingScrollToBottomId = targetConversationId
  try {
    await load(selectedId.value, true, selectedId.value === targetConversationId)
  } catch {
    notify('已加入发送队列，列表稍后自动刷新')
  }
}

function onComposerKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    void send()
  }
}

function refreshAllowed() {
  return !document.hidden && navigator.onLine
}

function onPageShow() {
  nowTick.value = Date.now()
  if (refreshAllowed()) refreshLoop?.start(true)
}

function onVisibilityChange() {
  nowTick.value = Date.now()
  if (refreshAllowed()) refreshLoop?.start(true)
  else {
    refreshLoop?.stop()
    cancelInboxRead()
  }
}

function onOffline() {
  refreshLoop?.stop()
  cancelInboxRead()
}

function onOnline() {
  if (refreshAllowed()) refreshLoop?.start(true)
}

onMounted(() => {
  let firstLoad = true
  refreshLoop = createInboxRefreshLoop(async () => {
    if (inboxReads.isBusy()) return
    try {
      await load(selectedId.value, true)
      firstLoad = false
    } catch (error) {
      if (firstLoad && !(error instanceof DOMException && error.name === 'AbortError')) {
        notify(`加载失败：${error instanceof Error ? error.message : String(error)}`)
        firstLoad = false
      }
      throw error
    }
  }, refreshAllowed)
  refreshLoop.start(true)
  clockTimer = window.setInterval(() => { nowTick.value = Date.now() }, 60_000)
  window.addEventListener('pageshow', onPageShow)
  window.addEventListener('pagehide', onOffline)
  window.addEventListener('online', onOnline)
  window.addEventListener('offline', onOffline)
  document.addEventListener('visibilitychange', onVisibilityChange)
})

onUnmounted(() => {
  refreshLoop?.stop()
  cancelInboxRead()
  if (toastTimer) window.clearTimeout(toastTimer)
  if (clockTimer) window.clearInterval(clockTimer)
  window.removeEventListener('pageshow', onPageShow)
  window.removeEventListener('pagehide', onOffline)
  window.removeEventListener('online', onOnline)
  window.removeEventListener('offline', onOffline)
  document.removeEventListener('visibilitychange', onVisibilityChange)
})
</script>


<template>
  <FluentTheme mode="system">
  <main class="mc-shell" :class="{ 'is-thread-open': mobileThread, 'is-instances-open': showInstances }">
    <aside class="nav-pane" aria-label="导航">
      <div class="brand">
        <span class="brand-mark" aria-hidden="true"><AppIcon name="brand" :size="18" /></span>
        <span class="brand-copy">
          <strong>Message Center</strong>
          <small><span class="presence-dot" :class="onlineConnectorCount ? 'online' : 'offline'" />{{ onlineConnectorCount }}/{{ snapshot.connectors.length }} 接入在线</small>
        </span>
      </div>

      <nav class="nav-scroll" aria-label="收件箱分类">
        <div class="nav-section">
          <p class="nav-label">收件箱</p>
          <button
            v-for="filter in filters"
            :key="filter.id"
            class="nav-item"
            :class="{ active: activeFilter === filter.id && !showInstances }"
            type="button"
            :title="filter.label"
            :aria-current="activeFilter === filter.id && !showInstances ? 'page' : undefined"
            :data-channel="filter.channel || undefined"
            :data-unread-count="filter.unread"
            @click="selectFilter(filter.id)"
          >
            <span
              class="nav-glyph"
              :class="filter.channel ? `channel-tone tone-${channelTone(filter.channel)}` : 'is-all'"
              :data-unread="filter.unread > 0 || undefined"
              aria-hidden="true"
            >
              <AppIcon v-if="!filter.channel" name="inbox" :size="16" />
              <template v-else>{{ channelGlyph(filter.channel) }}</template>
            </span>
            <span class="nav-copy">{{ filter.label }}</span>
            <span v-if="filter.unread" class="nav-count is-unread" aria-hidden="true">{{ filter.unread > 99 ? '99+' : filter.unread }}</span>
            <span v-else class="nav-count" aria-hidden="true">{{ filter.count }}</span>
            <span class="sr-only">，{{ filter.count }} 个会话，{{ filter.unread }} 条未读</span>
          </button>
        </div>

        <div class="nav-section management-nav">
          <p class="nav-label">管理</p>
          <button
            class="nav-item"
            :class="{ active: showInstances }"
            type="button"
            aria-label="接入管理"
            title="接入管理"
            :aria-current="showInstances ? 'page' : undefined"
            @click="showConnectorManagement"
          >
            <span class="nav-glyph is-system" :data-alert="onlineConnectorCount < snapshot.connectors.length || undefined" aria-hidden="true">
              <AppIcon name="settings" :size="16" />
            </span>
            <span class="nav-copy">接入管理</span>
            <span
              class="nav-count"
              :class="{ 'is-alert': onlineConnectorCount < snapshot.connectors.length }"
              aria-hidden="true"
            >{{ onlineConnectorCount }}/{{ snapshot.connectors.length }}</span>
          </button>
        </div>
      </nav>

      <div class="nav-footer">
        <a class="license-link" href="/vendor/fluent/NOTICE" target="_blank" rel="noreferrer">许可</a>
        <form method="post" action="/api/auth/logout">
          <button class="quiet-button logout-button" type="submit" aria-label="退出登录" title="退出登录">
            <AppIcon name="signOut" :size="18" />
          </button>
        </form>
      </div>
    </aside>

    <section v-if="!showInstances" class="conversation-pane" aria-label="会话列表">
      <header class="pane-header">
        <div class="pane-title">
          <h1>{{ activeFilterLabel }}</h1>
          <p aria-live="polite">
            {{ filteredConversations.length }} 个会话<template v-if="filteredUnread"> · <strong>{{ filteredUnread }}</strong> 条未读</template>
          </p>
        </div>
        <FluentButton
          class="quiet-button refresh-button"
          :class="{ spinning: manualRefreshing }"
          type="button"
          aria-label="刷新"
          title="刷新"
          @click="refreshNow"
        ><AppIcon name="refresh" :size="18" /></FluentButton>
      </header>

      <div ref="conversationListElement" class="conversation-list">
        <div class="conversation-list-tools">
          <div class="conversation-search">
            <AppIcon class="search-icon" name="search" :size="16" />
            <FluentField
              v-model="conversationSearch"
              label="搜索会话"
              type="search"
              placeholder="搜索名称或消息"
            />
          </div>
          <div class="segmented" role="group" aria-label="显示范围">
            <button
              type="button"
              :class="{ active: !unreadOnly }"
              :aria-pressed="!unreadOnly"
              title="显示全部会话"
              @click="unreadOnly = false"
            >全部</button>
            <button
              type="button"
              :class="{ active: unreadOnly }"
              :aria-pressed="unreadOnly"
              title="仅显示未读会话"
              @click="unreadOnly = true"
            >未读<span v-if="totalUnread" class="segmented-dot" aria-hidden="true" /></button>
          </div>
        </div>

        <ul class="conversation-items">
          <li v-for="conversation in conversationRows" :key="conversation.id">
            <button
              class="conversation-row"
              :class="{
                active: selectedId === conversation.id,
                pinned: conversation.pinned,
                folded: isFolded(conversation),
                unread: conversation.unreadCount > 0,
              }"
              type="button"
              :aria-current="selectedId === conversation.id ? 'true' : undefined"
              :data-conversation-id="conversation.id"
              :data-channel="conversation.channel"
              :data-conversation-type="conversation.conversationType || undefined"
              :data-unread-count="conversation.unreadCount"
              :data-pinned="conversation.pinned || undefined"
              @click="selectConversationById(conversation.id)"
            >
              <span class="avatar conversation-avatar" :class="`avatar-tone-${avatarTone(conversation.title)}`">
                <span aria-hidden="true">{{ initials(conversation.avatarLabel || conversation.title) }}</span>
                <img
                  v-if="conversation.avatarPath"
                  :key="avatarKey(conversation.avatarPath)"
                  :src="avatarSource(conversation.avatarPath)"
                  :data-avatar-path="conversation.avatarPath"
                  :data-avatar-revision="avatarRevision(conversation.avatarPath)"
                  alt=""
                  loading="lazy"
                  @load="imageLoaded"
                  @error="imageFailed"
                >
                <span
                  v-if="activeFilter === 'all' && !activeConnectorId"
                  class="channel-badge channel-tone"
                  :class="`tone-${channelTone(conversation.channel)}`"
                  aria-hidden="true"
                >{{ channelGlyph(conversation.channel) }}</span>
              </span>
              <span class="conversation-copy">
                <span class="conversation-title-row">
                  <strong>
                    <AppIcon v-if="conversation.conversationType === 'group'" class="title-icon" name="group" :size="14" />
                    <AppIcon v-if="isFolded(conversation)" class="title-icon" name="archive" :size="14" />
                    <span class="conversation-title">{{ conversation.title }}</span>
                  </strong>
                  <AppIcon v-if="conversation.pinned" class="pin-icon" name="pin" :size="12" />
                  <time
                    :datetime="isoTime(conversation.lastMessageAt)"
                    :title="formatFullStamp(conversation.lastMessageAt)"
                  >{{ listTime(conversation.lastMessageAt) }}</time>
                </span>
                <span class="conversation-meta-row">
                  <span class="conversation-preview">{{ conversationPreview(conversation) }}</span>
                  <span v-if="conversation.unreadCount" class="unread-count" aria-hidden="true">{{ conversation.unreadCount > 99 ? '99+' : conversation.unreadCount }}</span>
                </span>
                <span class="sr-only">，{{ conversation.channel }}<template v-if="conversationStateText(conversation)">，{{ conversationStateText(conversation) }}</template></span>
              </span>
            </button>
          </li>
        </ul>

        <div v-if="totalConversationPages > 1" class="conversation-pager">
          <FluentButton type="button" :disabled="conversationPage === 0" @click="showPreviousConversationPage">上一页</FluentButton>
          <span>{{ conversationRangeStart }}–{{ conversationRangeEnd }} / {{ filteredConversations.length }}</span>
          <FluentButton
            type="button"
            :disabled="conversationPage >= totalConversationPages - 1"
            @click="showNextConversationPage"
          >下一页</FluentButton>
        </div>
        <div v-if="!filteredConversations.length && !loading" class="empty-state">
          <span class="empty-glyph"><AppIcon :name="unreadOnly ? 'unread' : 'chat'" :size="22" /></span>
          <p>{{ conversationSearch.trim() ? '没有匹配的会话' : unreadOnly ? '没有未读会话' : '暂无会话' }}</p>
        </div>
        <div v-if="loading" class="loading-state"><span class="spinner" />正在载入</div>
      </div>
    </section>

    <section v-if="!showInstances" class="content-pane" aria-label="会话详情">
      <template v-if="selectedConversation">
        <header class="thread-header">
          <button class="quiet-button mobile-back" type="button" aria-label="返回收件箱" title="返回收件箱" @click="mobileThread = false">
            <AppIcon name="back" :size="18" />
          </button>
          <span class="avatar thread-avatar" :class="`avatar-tone-${avatarTone(selectedConversation.title)}`">
            <span aria-hidden="true">{{ initials(selectedConversation.avatarLabel || selectedConversation.title) }}</span>
            <img
              v-if="selectedConversation.avatarPath"
              :key="avatarKey(selectedConversation.avatarPath)"
              :src="avatarSource(selectedConversation.avatarPath)"
              :data-avatar-path="selectedConversation.avatarPath"
              :data-avatar-revision="avatarRevision(selectedConversation.avatarPath)"
              alt=""
              @load="imageLoaded"
              @error="imageFailed"
            >
          </span>
          <div class="thread-title">
            <h2>{{ selectedConversation.title }}</h2>
            <p class="thread-subtitle">
              <span class="channel-tag channel-tone" :class="`tone-${channelTone(channelLabel(selectedConversation))}`">{{ channelLabel(selectedConversation) }}</span>
              <span v-if="selectedConversation.conversationType === 'group'">群聊</span>
              <span v-else-if="selectedConversation.conversationType === 'direct'">私聊</span>
              <span class="presence" :class="selectedConversation.connectorState">
                <span class="presence-dot" :class="selectedConversation.connectorState" />接入{{ statusLabel(selectedConversation.connectorState) }}
              </span>
            </p>
          </div>
          <div
            v-if="threadAgentSummary.escalated || threadAgentSummary.working || threadAgentSummary.waiting"
            class="thread-agent-summary"
            aria-label="AI 处理概况"
          >
            <span v-if="threadAgentSummary.escalated" class="status-chip tone-warning" title="需人工处理"><AppIcon name="personAlert" :size="14" /><span class="chip-label">需人工</span> {{ threadAgentSummary.escalated }}</span>
            <span v-if="threadAgentSummary.working" class="status-chip tone-ai" title="AI 处理中"><AppIcon name="bot" :size="14" /><span class="chip-label">AI 处理中</span> {{ threadAgentSummary.working }}</span>
            <span v-if="threadAgentSummary.waiting" class="status-chip tone-muted" title="等待 AI 处理"><AppIcon name="hourglass" :size="14" /><span class="chip-label">待 AI</span> {{ threadAgentSummary.waiting }}</span>
          </div>
        </header>

        <div class="message-scroll" :class="{ busy: detailLoading }" role="log" aria-label="消息记录" :aria-busy="detailLoading">
          <template v-for="entry in threadRows" :key="entry.key">
            <div v-if="entry.kind === 'day'" class="day-divider">
              <time :datetime="entry.dateTime">{{ entry.label }}</time>
            </div>
            <article
              v-else
              :data-message-id="entry.message.id"
              class="message-row"
              :class="[entry.message.direction, { continuation: entry.continuation, 'by-agent': entry.byAgent }]"
              :data-direction="entry.message.direction"
              :data-author-role="entry.message.authorRole || undefined"
              :data-delivery-state="entry.message.direction === 'outbound' ? entry.message.deliveryState || undefined : undefined"
              :data-agent-state="entry.message.agentState || undefined"
            >
              <span
                class="avatar message-avatar"
                :class="entry.byAgent ? 'avatar-agent' : `avatar-tone-${avatarTone(entry.message.senderName)}`"
              >
                <AppIcon v-if="entry.byAgent" name="bot" :size="16" />
                <span v-else aria-hidden="true">{{ initials(entry.message.senderName) }}</span>
                <img
                  v-if="entry.message.senderAvatarPath && !entry.byAgent"
                  :key="avatarKey(entry.message.senderAvatarPath)"
                  :src="avatarSource(entry.message.senderAvatarPath)"
                  :data-avatar-path="entry.message.senderAvatarPath"
                  :data-avatar-revision="avatarRevision(entry.message.senderAvatarPath)"
                  alt=""
                  loading="lazy"
                  decoding="async"
                  @load="imageLoaded"
                  @error="imageFailed"
                >
              </span>
              <div class="message-block">
                <p class="message-meta" :class="{ 'sr-only': entry.continuation }">
                  <span class="message-sender">{{ senderLabel(entry.message) }}</span>
                  <span v-if="entry.byAgent" class="role-chip"><AppIcon name="bot" :size="12" />代你发送</span>
                  <time
                    :datetime="isoTime(entry.message.occurredAt)"
                    :title="formatFullStamp(entry.message.occurredAt)"
                  >{{ formatClock(entry.message.occurredAt) }}</time>
                </p>
                <div class="message-bubble" :title="entry.continuation ? formatFullStamp(entry.message.occurredAt) : undefined">
                  <p v-if="messageBody(entry.message)">{{ messageBody(entry.message) }}</p>
                  <div v-for="file in entry.message.attachments" :key="file.id" class="attachment">
                    <img
                      v-if="isImage(file)"
                      class="attachment-image"
                      :src="filePath(file)"
                      :alt="file.fileName"
                      loading="lazy"
                      @load="setAttachmentImageLoaded(entry.message, file, true)"
                      @error="setAttachmentImageLoaded(entry.message, file, false)"
                    >
                    <video v-else-if="isVideo(file)" class="attachment-video" :src="filePath(file)" controls preload="metadata" />
                    <a v-else-if="file.downloadable" class="attachment-link" :href="filePath(file)" :download="file.fileName">
                      <span class="file-icon"><AppIcon name="document" :size="18" /></span>
                      <span class="file-copy"><strong>{{ file.fileName }}</strong><small>{{ formatBytes(file.sizeBytes) }}</small></span>
                      <AppIcon class="file-action" name="download" :size="16" />
                    </a>
                    <span v-else class="attachment-link pending">
                      <span class="file-icon"><AppIcon name="document" :size="18" /></span>
                      <span class="file-copy"><strong>{{ file.fileName }}</strong><small>等待上传</small></span>
                    </span>
                  </div>
                </div>
                <p v-if="entry.delivery || entry.agent" class="message-status">
                  <span v-if="entry.delivery" class="message-delivery-state" :class="`tone-${entry.delivery.tone}`"><AppIcon :name="entry.delivery.icon" :size="12" />{{ entry.delivery.label }}</span>
                  <span
                    v-if="entry.agent"
                    class="message-agent-state"
                    :class="[`tone-${entry.agent.tone}`, { compact: entry.message.agentState === 'completed' }]"
                    :title="entry.agent.label"
                  ><AppIcon :name="entry.agent.icon" :size="12" /><span class="status-text">{{ entry.agent.label }}</span></span>
                </p>
              </div>
            </article>
          </template>

          <div v-if="!snapshot.messages.length && !detailLoading" class="empty-state thread-empty">
            <span class="empty-glyph"><AppIcon name="chat" :size="22" /></span>
            <p>{{ hasKnownConversationActivity ? '消息内容尚未同步' : '暂无消息' }}</p>
          </div>
          <div v-if="detailLoading" class="loading-overlay"><span class="spinner" /></div>
        </div>

        <footer class="composer">
          <div v-if="staged.length" class="staged-files" aria-label="待发送附件">
            <button
              v-for="(file, index) in staged"
              :key="file.id"
              type="button"
              :aria-label="`移除附件 ${file.fileName}`"
              :title="`移除 ${file.fileName}`"
              @click="removeStaged(index)"
            >
              <AppIcon name="document" :size="14" />
              <span>{{ file.fileName }}</span>
              <AppIcon class="staged-remove" name="dismiss" :size="12" />
            </button>
          </div>
          <div class="compose-surface" :class="{ disabled: !canSendText }">
            <textarea
              v-model="draft"
              :disabled="!canSendText"
              :maxlength="maxTextLength"
              :placeholder="canSendText ? `回复 ${selectedConversation.title}` : '此接入仅接收消息'"
              :aria-label="`回复 ${selectedConversation.title}`"
              rows="2"
              @keydown="onComposerKeydown"
            />
            <div class="compose-toolbar">
              <label
                class="quiet-button attachment-button"
                :class="{ disabled: !canSendFiles || uploadingConversationIds.has(selectedId) }"
                title="添加附件"
              >
                <AppIcon name="attach" :size="18" />
                <input
                  type="file"
                  multiple
                  aria-label="添加附件"
                  :accept="fileAccept"
                  :disabled="!canSendFiles || uploadingConversationIds.has(selectedId)"
                  @change="uploadFiles"
                >
              </label>
              <span v-if="uploadingConversationIds.has(selectedId)" class="capability-hint"><span class="spinner small" />正在上传</span>
              <span v-else-if="!canSendFiles && canSendText" class="capability-hint">此会话不支持发送附件</span>
              <span
                v-if="canSendText && deviceConversation && draft.length > maxTextLength * 0.8"
                class="char-count"
                aria-live="polite"
              >{{ draft.length }}/{{ maxTextLength }}</span>
              <span v-if="canSendText" class="compose-hint">Enter 发送 · Shift+Enter 换行</span>
              <FluentButton class="accent-button" tone="primary" type="button" :disabled="!canSend" @click="send">
                <AppIcon name="send" :size="16" /><span>发送</span>
              </FluentButton>
            </div>
          </div>
        </footer>
      </template>

      <div v-else class="empty-state welcome-state">
        <span class="empty-glyph"><AppIcon name="chat" :size="22" /></span>
        <p>选择一个会话</p>
      </div>
    </section>

    <section v-else class="instances-pane" aria-label="接入管理">
      <header class="instances-header">
        <button class="quiet-button" type="button" aria-label="返回收件箱" title="返回收件箱" @click="showInstances = false">
          <AppIcon name="back" :size="18" />
        </button>
        <div>
          <h1>接入管理</h1>
          <p>{{ snapshot.connectors.length }} 个账号 · {{ onlineConnectorCount }} 个在线</p>
        </div>
      </header>
      <div class="instance-grid">
        <article
          v-for="connector in snapshot.connectors"
          :key="connector.id"
          class="instance-card"
          :class="connector.state"
          :data-connector-id="connector.id"
          :data-state="connector.state"
        >
          <header>
            <span class="instance-glyph channel-tone" :class="`tone-${channelTone(channelLabel(connector))}`" aria-hidden="true">{{ channelGlyph(channelLabel(connector)) }}</span>
            <div class="instance-heading">
              <p>{{ channelLabel(connector) }}</p>
              <h2>{{ connector.accountLabel }}</h2>
            </div>
            <span class="status-pill" :class="connector.state">
              <span class="presence-dot" :class="connector.state" />{{ statusLabel(connector.state) }}
            </span>
          </header>
          <p v-if="connector.lastSeenAt" class="instance-seen">
            <AppIcon :name="connector.state === 'online' ? 'plugConnected' : 'plugDisconnected'" :size="14" />
            最近活动
            <time :datetime="isoTime(connector.lastSeenAt)" :title="formatFullStamp(connector.lastSeenAt)">{{ relativeAge(connector.lastSeenAt) }}</time>
          </p>
          <dl>
            <dt>账号</dt><dd>{{ connector.accountLabel }}</dd>
            <dt>渠道</dt><dd>{{ channelLabel(connector) }}</dd>
            <dt>ID</dt><dd class="mono">{{ connector.id }}</dd>
            <dt>模式</dt><dd>{{ modeLabel(connector.mode) }}<span v-if="modeLabel(connector.mode) !== connector.mode" class="mono mode-code">{{ connector.mode }}</span></dd>
            <dt>能力</dt>
            <dd class="capability-list">
              <span
                v-for="group in capabilityGroups(connector.capabilities)"
                :key="group.id"
                class="capability-group"
                :class="`is-${group.id}`"
              >
                <span class="capability-group-label">{{ group.label }}</span>
                <span v-for="capability in group.items" :key="capability" class="capability-chip">{{
                  group.id === 'other' ? capLabel(capability) : capLabel(capability).replace(/^[收发]/, '')
                }}</span>
              </span>
              <span v-if="!connector.capabilities.length" class="capability-chip">未声明</span>
            </dd>
          </dl>
          <section v-if="supportsLayoutAutoRecovery(connector)" class="instance-control" aria-label="布局控制">
            <div class="instance-control-copy">
              <strong>自动恢复布局</strong>
              <span>{{ layoutControlStatus(connector) }}</span>
            </div>
            <FluentSwitch
              class="toggle-switch"
              :model-value="connectorLayoutControl(connector).enabled"
              :aria-label="`${connector.accountLabel} 自动恢复布局`"
              :disabled="updatingLayoutConnectorIds.has(connector.id)"
              @change="setLayoutAutoRecovery(connector, $event)"
            />
          </section>
          <footer class="instance-actions">
            <FluentButton
              class="instance-open-button"
              tone="subtle"
              type="button"
              :disabled="!snapshot.conversations.some((conversation) => conversation.connectorId === connector.id)"
              @click="selectFilter(`channel:${channelLabel(connector)}`, connector.id)"
            ><span>查看此账号会话</span><AppIcon name="arrowRight" :size="14" /></FluentButton>
          </footer>
        </article>
        <div v-if="!snapshot.connectors.length && !loading" class="empty-state">
          <span class="empty-glyph"><AppIcon name="plugDisconnected" :size="22" /></span>
          <p>尚无接入实例</p>
        </div>
      </div>
    </section>
  </main>

  <Transition name="toast">
    <div v-if="toast" class="toast" role="status">{{ toast }}</div>
  </Transition>
</FluentTheme>
</template>
