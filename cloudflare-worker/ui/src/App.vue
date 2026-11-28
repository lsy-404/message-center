<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { FluentButton, FluentField, FluentTheme } from '@platform-kit/fluent/vue'
import AppIcon from './AppIcon.vue'
import type { IconName } from './icons'
import { createInboxReadGate, createInboxRefreshLoop } from './inbox-refresh.mjs'
import { createLiveSignal } from './live-signal.mjs'
import {
  clearPendingSendRequestKey,
  getPendingSendRequestKey,
  isAcceptedSendResponse,
} from './send-request-key.mjs'
import {
  aggregateContacts,
  buildConversationListModel,
  canEnterConversationListFolder,
  CONTACT_ROW_PREFIX,
  CONVERSATION_PAGE_SIZE,
  conversationPageCount,
  enterConversationListFolder,
  filterConversations,
  MAX_CONVERSATION_LIST_LEVELS,
  normalizeChannelLabel,
  nextConversationPage,
  pageConversations,
  previousConversationPage,
  conversationFolderOf,
  getConversationFolder,
  unreadTotal,
  resolveConversationSelection,
} from './conversation-list.mjs'
import {
  avatarTone,
  buildThreadEntries,
  channelGlyph,
  channelIcon,
  channelTone,
  formatClock,
  formatFullStamp,
  formatListTime,
  formatRelativeAge,
} from './presentation.mjs'
import { parseMessageBody, previewText, type CardKind, type MediaKind, type MoneyKind } from './rich-body.mjs'

type ConnectorState = 'online' | 'offline' | 'degraded'

type AgentAccess = 'none' | 'read' | 'send'

type FilterRule = { type: 'sender' | 'body' | 'regex', pattern: string }

type FilterSettings = {
  enabled: boolean
  linkDrop: boolean
  spamKeywords: boolean
  customRules: FilterRule[]
  allowlist: string[]
}

type FilterDraft = Omit<FilterSettings, 'allowlist'> & { allowlistText: string, dirty: boolean }

type FilteredMessage = {
  id: string
  connectorId: string
  channelLabel: string
  accountLabel: string
  conversationTitle: string
  senderName: string
  body: string
  occurredAt: string
  rule: string
  detail: string
}

type Connector = {
  id: string
  kind: string
  channelLabel?: string | null
  accountLabel: string
  displayName: string
  mode: string
  state: ConnectorState
  capabilities: string[]
  lastSeenAt?: string | null
  native: boolean
  nativeDesktop: string | null
  agentAccess: AgentAccess
  filter: FilterSettings
}

type Contact = {
  id: string
  name: string
  note: string
  conversationIds: string[]
  defaultConversationId: string
}

type ContactSuggestion = {
  key: string
  name: string
  contactId: string | null
  conversationIds: string[]
}

type Conversation = {
  id: string
  connectorId: string
  connectorKind: string
  connectorChannelLabel?: string | null
  conversationType?: string | null
  placement?: string | null
  pinned?: boolean
  muted?: boolean
  title: string
  avatarLabel?: string | null
  avatarPath?: string | null
  unreadCount: number
  lastMessagePreview?: string | null
  lastMessageAt?: string | null
  connectorState: ConnectorState
  capabilities: string[]
  contactId?: string
  members?: Conversation[]
}

type ConversationListItem = Pick<Conversation,
  'id' | 'title' | 'avatarLabel' | 'avatarPath' | 'unreadCount' | 'lastMessagePreview' | 'lastMessageAt' | 'placement'
  | 'pinned' | 'muted' | 'conversationType' | 'contactId'
> & { channel: string, channels: string[] }

type Attachment = {
  id: string
  fileName: string
  mimeType?: string | null
  sizeBytes?: number | null
  downloadable?: boolean
  presentation?: 'sticker'
}

type ReplyPreview = {
  sourceText: string
  sourceTextTruncated: boolean
  sourceExpired: boolean
}

type Message = {
  id: string
  conversationId: string
  connectorId?: string
  channelLabel?: string
  accountLabel?: string
  direction: 'inbound' | 'outbound' | string
  senderName: string
  senderAvatarPath?: string | null
  body: string
  reply?: ReplyPreview | null
  presentation?: 'system'
  contentType: string
  occurredAt: string
  deliveryState?: string | null
  queueClass?: string | null
  authorRole?: 'contact' | 'owner' | 'agent' | string | null
  agentRead?: boolean | null
  attachments: Attachment[]
}

type StatusInfo = { label: string, tone: 'muted' | 'success' | 'warning' | 'danger', icon: IconName }

type Snapshot = {
  connectors: Connector[]
  conversations: Conversation[]
  contacts: Contact[]
  messages: Message[]
  selectedConversationId: string | null
  filteredCount: number
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

const emptySnapshot = (): Snapshot => ({ connectors: [], conversations: [], contacts: [], messages: [], selectedConversationId: null, filteredCount: 0 })
const snapshot = ref<Snapshot>(emptySnapshot())
const initialConversationId = new URLSearchParams(window.location.search).get('conversation') || ''
const selectedId = ref(initialConversationId)
const selectedContactId = ref('')
const activeFilter = ref('all')
const activeConnectorId = ref('')
const conversationListPath = ref<string[]>([])
const conversationSearch = ref('')
const unreadOnly = ref(false)
const manualRefreshing = ref(false)
const nowTick = ref(Date.now())
const conversationPage = ref(0)
const conversationListElement = ref<HTMLElement | null>(null)
const showInstances = ref(false)
const showFiltered = ref(false)
const filteredMessages = ref<FilteredMessage[]>([])
const filteredLoading = ref(false)
const filterDrafts = ref<Record<string, FilterDraft>>({})
const overlayPane = computed(() => showInstances.value || showFiltered.value)
const mobileThread = ref(Boolean(initialConversationId))
const loading = ref(true)
const detailLoading = ref(false)
const draft = ref('')
const staged = ref<StagedAttachment[]>([])
const toast = ref('')
const inboxReads = createInboxReadGate()
let inboxTimeout: number | undefined
let refreshLoop: ReturnType<typeof createInboxRefreshLoop> | undefined
const liveSignal = createLiveSignal(() => { if (refreshAllowed()) refreshLoop?.wake() })
let toastTimer: number | undefined
let clockTimer: number | undefined
let pendingScrollToBottomId: string | null = null
const draftCache = new Map<string, string>()
const stagedCache = new Map<string, StagedAttachment[]>()
const sendingConversationIds = ref(new Set<string>())
const uploadingConversationIds = ref(new Set<string>())
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
const selectedContact = computed(() =>
  snapshot.value.contacts.find((item) => item.id === selectedContactId.value) ?? null,
)
const contactMembers = computed(() => (selectedContact.value?.conversationIds ?? [])
  .map((id) => snapshot.value.conversations.find((item) => item.id === id))
  .filter((item): item is Conversation => Boolean(item)))
const selectionKey = computed(() => selectedContactId.value
  ? `${CONTACT_ROW_PREFIX}${selectedContactId.value}` : selectedId.value)
const listItems = computed<Conversation[]>(() =>
  aggregateContacts(snapshot.value.conversations, snapshot.value.contacts) as Conversation[],
)
const nativeDesktops = computed(() => {
  const groups = new Map<string, { key: string, connectors: Connector[] }>()
  for (const connector of snapshot.value.connectors) {
    if (!connector.native) continue
    const key = connector.nativeDesktop || connector.id
    const group = groups.get(key)
    if (group) group.connectors.push(connector)
    else groups.set(key, { key, connectors: [connector] })
  }
  const desktops = [...groups.values()].map((group) => {
    const ids = new Set(group.connectors.map((connector) => connector.id))
    return {
      key: group.key,
      channel: [...new Set(group.connectors.map((connector) => channelLabel(connector)))].join(' · '),
      account: group.connectors.map((connector) => connector.accountLabel).join(' · '),
      unread: unreadTotal(snapshot.value.conversations.filter((item) => ids.has(item.connectorId))),
      connector: group.connectors[0],
      src: `/native/${encodeURIComponent(group.connectors[0].id)}/`,
    }
  })
  return desktops.map((desktop) => ({
    ...desktop,
    label: desktops.filter((item) => item.channel === desktop.channel).length > 1
      ? `${desktop.channel} · ${desktop.account}` : desktop.channel,
  }))
})
const activeNativeDesktop = computed(() =>
  nativeDesktops.value.find((item) => item.key === nativeDesktopKey.value) ?? nativeDesktops.value[0] ?? null,
)
const nativeViewActive = computed(() => viewMode.value === 'native' && !!activeNativeDesktop.value)
const filters = computed(() => {
  const labels = new Map<string, string>()
  for (const conversation of snapshot.value.conversations) {
    if (conversation.connectorKind === 'qq') continue
    const label = channelLabel(conversation)
    labels.set(label, label)
  }
  const summarize = (items: Conversation[]) => ({
    count: items.length,
    unread: unreadTotal(items),
  })
  const qqConversations = snapshot.value.conversations.filter((item) => item.connectorKind === 'qq')
  return [
    { id: 'all', label: '全部', channel: '', ...summarize(listItems.value) },
    ...(qqConversations.length ? [{
      id: 'protocol:qq', label: 'QQ', channel: 'QQ', ...summarize(qqConversations),
    }] : []),
    ...[...labels.values()].map((label) => ({
      id: `channel:${label}`,
      label,
      channel: label,
      ...summarize(snapshot.value.conversations.filter((item) => channelLabel(item) === label)),
    })),
  ]
})
const onlineConnectorCount = computed(() => snapshot.value.connectors.filter((item) => item.state === 'online').length)
const degradedConnectorCount = computed(() => snapshot.value.connectors.filter((item) => item.state === 'degraded').length)
const activeFilterLabel = computed(() => {
  if (activeFilter.value === 'protocol:qq') return 'QQ'
  if (activeConnectorId.value) {
    const connector = snapshot.value.connectors.find((item) => item.id === activeConnectorId.value)
    if (connector) return connector.accountLabel
  }
  return activeFilter.value === 'all' ? '收件箱' : activeFilter.value.slice('channel:'.length)
})
const isQQRootScope = computed(() => activeFilter.value === 'protocol:qq'
  || (activeFilter.value.startsWith('channel:')
    && normalizeChannelLabel(activeFilter.value.slice('channel:'.length)) === 'QQ'))
const isWeChatRootScope = computed(() => activeFilter.value.startsWith('channel:')
  && normalizeChannelLabel(activeFilter.value.slice('channel:'.length)) === '微信')
const folderScopeKinds = computed<Array<'qq' | 'wechat'>>(() => {
  const connector = activeConnectorId.value
    ? snapshot.value.connectors.find((item) => item.id === activeConnectorId.value)
    : undefined
  if (connector) return connector.kind === 'qq' || connector.kind === 'wechat' ? [connector.kind] : []
  if (activeFilter.value === 'all') return ['qq', 'wechat']
  return isQQRootScope.value ? ['qq'] : isWeChatRootScope.value ? ['wechat'] : []
})
const conversationFilterOptions = () => ({
  connectorKind: activeFilter.value === 'protocol:qq' ? 'qq' : undefined,
  connectorId: activeConnectorId.value,
  channelLabel: activeFilter.value === 'all' || activeFilter.value === 'protocol:qq'
    ? '' : activeFilter.value.slice('channel:'.length),
  query: conversationSearch.value,
  unreadOnly: unreadOnly.value,
  getChannelLabel: channelLabel,
})
const filteredConversations = computed(() => filterConversations(
  listItems.value, conversationFilterOptions(),
))
const conversationListModel = computed(() => buildConversationListModel(filteredConversations.value, {
  path: conversationListPath.value,
  scopeKinds: folderScopeKinds.value,
  selectedId: selectionKey.value,
  rootTitle: activeFilterLabel.value,
}))
const displayedConversations = computed(() => conversationListModel.value.conversations)
const displayedUnread = computed(() => unreadTotal(conversationListModel.value.scopeConversations))
const displayedConversationCount = computed(() => conversationListModel.value.scopeConversations.length)
const listFolders = computed(() => conversationListModel.value.folders)
const conversationListTitle = computed(() => conversationListPath.value.length
  ? getConversationFolder(conversationListPath.value[0])?.title ?? '' : activeFilterLabel.value)
const conversationListBreadcrumbs = computed(() => [
  activeFilterLabel.value,
  ...conversationListPath.value.map((folderId) => getConversationFolder(folderId)?.title ?? ''),
].filter(Boolean))
const visibleConversations = computed(() => pageConversations(
  displayedConversations.value,
  conversationPage.value,
  CONVERSATION_PAGE_SIZE,
))
const totalConversationPages = computed(() => conversationPageCount(displayedConversations.value.length))
const conversationRangeStart = computed(() => displayedConversations.value.length
  ? conversationPage.value * CONVERSATION_PAGE_SIZE + 1 : 0)
const conversationRangeEnd = computed(() => Math.min(
  (conversationPage.value + 1) * CONVERSATION_PAGE_SIZE,
  displayedConversations.value.length,
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
  muted: conversation.muted,
  conversationType: conversation.conversationType,
  contactId: conversation.contactId,
  channel: channelLabel(conversation),
  channels: conversation.members
    ? [...new Set(conversation.members.map((member) => channelLabel(member)))] : [],
})))

watch([activeFilter, activeConnectorId, conversationSearch, unreadOnly, conversationListPath], async () => {
  conversationPage.value = 0
  await nextTick()
  conversationListElement.value?.scrollTo(0, 0)
  if (conversationListPath.value.length) {
    applyConversationSelection(conversationListModel.value.selectionConversations)
  }
})

const threadEntries = computed(() => buildThreadEntries(snapshot.value.messages, nowTick.value))
const aiUnreadCount = computed(() => snapshot.value.messages
  .filter((message) => message.direction !== 'outbound' && message.agentRead === false).length)

const threadRows = computed(() => threadEntries.value.map((entry) => {
  if (entry.kind === 'day') return entry
  const blocks = parseMessageBody(messageBody(entry.message)).filter((block) =>
    !entry.message.reply || block.type !== 'quote' || block.author || block.text,
  )
  const solo = blocks.length === 1 && !entry.message.attachments.length ? blocks[0] : null
  const explicitSystemText = entry.message.presentation === 'system' && entry.message.direction === 'inbound'
      && entry.message.attachments.length === 0 && entry.message.body.trim()
    ? entry.message.body : ''
  return {
    ...entry,
    byAgent: isAgentMessage(entry.message),
    delivery: deliveryStateInfo(entry.message),
    aiRead: entry.message.direction === 'outbound' ? null : entry.message.agentRead ?? null,
    blocks,
    // A lone pat reads as a system line; a lone card or transfer is its own bubble.
    systemText: explicitSystemText || (solo?.type === 'notice' ? solo.text : ''),
    systemPresentation: explicitSystemText ? 'system' : solo?.type === 'notice' ? 'notice' : '',
    bare: solo?.type === 'card' || solo?.type === 'money',
  }
}))

const hasKnownConversationActivity = computed(() => Boolean(
  selectedConversation.value?.lastMessageAt || selectedConversation.value?.lastMessagePreview?.trim(),
))

const connectorReachable = computed(() => selectedConversationConnector.value?.state === 'online'
  || selectedConversationConnector.value?.state === 'degraded')
const canSendText = computed(() => Boolean(connectorReachable.value && selectedConversation.value?.capabilities.includes('send_text')))
const deviceConversation = computed(() => selectedConversationConnector.value?.mode === 'device_relay')
const maxTextLength = computed(() => deviceConversation.value ? 500 : 20_000)
const canSendFiles = computed(() => {
  if (!connectorReachable.value) return false
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
    threads: '会话串', reactions: '回应',
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
  if (state === 'online') return '在线'
  if (state === 'degraded') return '部分同步'
  return '离线'
}

function statusIcon(state: ConnectorState) {
  return state === 'online' ? 'plugConnected' : state === 'degraded' ? 'warning' : 'plugDisconnected'
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

const CARD_ICONS: Record<CardKind, IconName> = {
  miniprogram: 'miniProgram', link: 'link', app: 'miniProgram', forward: 'forward', channels: 'channels',
  music: 'music', location: 'location', contact: 'contact', article: 'article',
}
const MEDIA_ICONS: Record<MediaKind, IconName> = {
  image: 'image', voice: 'voice', video: 'video', file: 'file', sticker: 'sticker', unknown: 'unknown',
}
const MONEY_ICONS: Record<MoneyKind, IconName> = { transfer: 'money', redpacket: 'gift' }

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
    conversation.muted ? '免打扰' : '',
    conversation.conversationType === 'group' ? '群聊' : '',
    conversation.placement === 'message_box' ? '消息盒子' : conversation.placement === 'folded' ? '折叠聊天' : '',
    conversation.unreadCount ? `${conversation.unreadCount} 条未读` : '',
  ].filter(Boolean).join('，')
}

function conversationPreview(conversation: ConversationListItem) {
  const preview = previewText(conversation.lastMessagePreview)
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

function isSticker(file: Attachment) {
  return isImage(file) && file.presentation === 'sticker'
}

function isVideo(file: Attachment) {
  return Boolean(file.downloadable && file.mimeType?.startsWith('video/'))
}

function messageBody(message: Message) {
  let loadedPhotoCount = message.attachments.filter((file) =>
    isImage(file) && !isSticker(file) && loadedAttachmentImages.value.has(`${message.id}:${file.id}`),
  ).length
  let loadedStickerCount = message.attachments.filter((file) =>
    isSticker(file) && loadedAttachmentImages.value.has(`${message.id}:${file.id}`),
  ).length
  if (!loadedPhotoCount && !loadedStickerCount) return message.body || ''
  return (message.body || '').split(/\r?\n/).filter((line) => {
    if (loadedPhotoCount > 0 && /^[ \t]*\[图片\][ \t]*$/.test(line)) {
      loadedPhotoCount -= 1
      return false
    }
    if (loadedStickerCount > 0 && /^[ \t]*\[表情\][ \t]*$/.test(line)) {
      loadedStickerCount -= 1
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

const pushSupported = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
const iosNeedsInstall = (/iPhone|iPad|iPod/.test(navigator.userAgent)
  || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1))
  && !((navigator as Navigator & { standalone?: boolean }).standalone === true
    || window.matchMedia('(display-mode: standalone)').matches)
const pushEnabled = ref(false)
const pushBusy = ref(false)
const pushDevices = ref<{ endpoint: string, label: string, createdAt: string, lastSuccessAt: string | null }[]>([])

function vapidKeyBytes(key: string) {
  const base64 = key.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(key.length / 4) * 4, '=')
  return Uint8Array.from(atob(base64), (char) => char.charCodeAt(0))
}

async function currentPushSubscription() {
  const registration = await navigator.serviceWorker.getRegistration('/')
  return registration ? registration.pushManager.getSubscription() : null
}

async function refreshPush() {
  if (!pushSupported) return
  try {
    const body = await api<{ devices: typeof pushDevices.value }>('/api/push/subscriptions')
    pushDevices.value = body.devices
    const subscription = await currentPushSubscription()
    pushEnabled.value = Boolean(subscription && body.devices.some((device) => device.endpoint === subscription.endpoint))
  } catch { /* the section stays in its last known state */ }
}

async function enablePush() {
  pushBusy.value = true
  try {
    if (await Notification.requestPermission() !== 'granted') {
      notify('未获得通知权限，请在系统设置中允许')
      return
    }
    const { publicKey } = await api<{ publicKey: string | null }>('/api/push/public-key')
    if (!publicKey) {
      notify('服务器尚未配置推送密钥')
      return
    }
    const registration = await navigator.serviceWorker.ready
    const subscription = await registration.pushManager.getSubscription()
      ?? await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: vapidKeyBytes(publicKey) })
    await api('/api/push/subscriptions', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(subscription.toJSON()),
    })
    await refreshPush()
    notify('已开启手机通知')
  } catch (error) {
    notify(`开启失败：${error instanceof Error ? error.message : String(error)}`)
  } finally {
    pushBusy.value = false
  }
}

async function disablePush() {
  pushBusy.value = true
  try {
    const subscription = await currentPushSubscription()
    if (subscription) {
      await api('/api/push/subscriptions', {
        method: 'DELETE',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ endpoint: subscription.endpoint }),
      })
      await subscription.unsubscribe()
    }
    await refreshPush()
    notify('已关闭本设备的手机通知')
  } catch (error) {
    notify(`关闭失败：${error instanceof Error ? error.message : String(error)}`)
  } finally {
    pushBusy.value = false
  }
}

async function sendTestPush() {
  pushBusy.value = true
  try {
    const result = await api<{ sent: number }>('/api/push/test', { method: 'POST' })
    notify(result.sent ? '测试通知已发送' : '没有可用的已订阅设备')
  } catch (error) {
    notify(`发送失败：${error instanceof Error ? error.message : String(error)}`)
  } finally {
    pushBusy.value = false
  }
}

function sameInbox(left: Snapshot, right: Snapshot) {
  if (left.selectedConversationId !== right.selectedConversationId
      || left.filteredCount !== right.filteredCount) return false
  if (left.connectors.length !== right.connectors.length
      || left.conversations.length !== right.conversations.length
      || left.messages.length !== right.messages.length
      || JSON.stringify(left.contacts) !== JSON.stringify(right.contacts)) return false
  for (let index = 0; index < left.connectors.length; index += 1) {
    const a = left.connectors[index]
    const b = right.connectors[index]
    if (a.id !== b.id || a.accountLabel !== b.accountLabel || a.displayName !== b.displayName
        || a.channelLabel !== b.channelLabel || a.mode !== b.mode || a.state !== b.state
        || a.lastSeenAt !== b.lastSeenAt || a.native !== b.native || a.nativeDesktop !== b.nativeDesktop
        || a.agentAccess !== b.agentAccess || JSON.stringify(a.filter) !== JSON.stringify(b.filter)
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
        || a.pinned !== b.pinned || a.muted !== b.muted || a.connectorState !== b.connectorState
        || a.capabilities.length !== b.capabilities.length
        || a.capabilities.some((value, itemIndex) => value !== b.capabilities[itemIndex])) return false
  }
  for (let index = 0; index < left.messages.length; index += 1) {
    const a = left.messages[index]
    const b = right.messages[index]
    if (a.id !== b.id || a.conversationId !== b.conversationId || a.direction !== b.direction
        || a.senderName !== b.senderName
        || a.senderAvatarPath !== b.senderAvatarPath
        || a.body !== b.body || a.contentType !== b.contentType || a.occurredAt !== b.occurredAt
        || a.deliveryState !== b.deliveryState || a.queueClass !== b.queueClass
        || a.authorRole !== b.authorRole || a.agentRead !== b.agentRead
        || a.reply?.sourceText !== b.reply?.sourceText
        || a.reply?.sourceTextTruncated !== b.reply?.sourceTextTruncated
        || a.reply?.sourceExpired !== b.reply?.sourceExpired
        || a.attachments.length !== b.attachments.length) return false
    for (let attachmentIndex = 0; attachmentIndex < a.attachments.length; attachmentIndex += 1) {
      const file = a.attachments[attachmentIndex]
      const nextFile = b.attachments[attachmentIndex]
      if (file.id !== nextFile.id || file.fileName !== nextFile.fileName
          || file.mimeType !== nextFile.mimeType || file.sizeBytes !== nextFile.sizeBytes
          || file.downloadable !== nextFile.downloadable
          || file.presentation !== nextFile.presentation) return false
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
  if (selectedContactId.value) query.set('contactId', selectedContactId.value)
  try {
    const body = await api<Snapshot & { ok: boolean }>(`/api/inbox?${query}`, { signal: request.controller.signal })
    if (!inboxReads.isCurrent(request, selectedId.value)) return
    let reloadConversationId = ''
    if (selectedContactId.value) {
      const contact = body.contacts.find((item) => item.id === selectedContactId.value)
      if (!contact) {
        selectedContactId.value = ''
      } else if (!contact.conversationIds.includes(body.selectedConversationId || '')) {
        body.selectedConversationId = contact.defaultConversationId
        reloadConversationId = contact.defaultConversationId
        body.messages = []
      }
    } else if (!conversationListPath.value.length && body.selectedConversationId) {
      const owner = body.contacts.find((item) => item.conversationIds.includes(body.selectedConversationId || ''))
      if (owner) {
        selectedContactId.value = owner.id
        reloadConversationId = body.selectedConversationId
        body.messages = []
      }
    }
    if (conversationListPath.value.length) {
      const scopedConversations = filterConversations(
        aggregateContacts(body.conversations, body.contacts), conversationFilterOptions(),
      )
      const listModel = buildConversationListModel(scopedConversations, {
        path: conversationListPath.value,
        scopeKinds: folderScopeKinds.value,
        selectedId: selectionKey.value,
      })
      const selection = resolveConversationSelection(listModel.selectionConversations, selectionKey.value)
      const selectedConversationId = selection.action === 'keep'
        ? selectedId.value
        : selection.action === 'select' ? selection.conversation?.id || '' : ''
      body.selectedConversationId = selectedConversationId
      reloadConversationId = selectedConversationId && selectedConversationId !== request.conversationId
        ? selectedConversationId : ''
      if (reloadConversationId || !selectedConversationId) body.messages = []
    }
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
    if (sameInbox(snapshot.value, body)) {
      if (reloadConversationId) void load(reloadConversationId, true)
      return
    }
    snapshot.value = body
    await nextTick()
    if (!inboxReads.isActive(request)) return
    if (reloadConversationId) {
      void load(reloadConversationId, true)
      return
    }
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

async function selectConversation(conversation: Conversation, openMobileThread = true, contactId = '') {
  const folder = contactId ? null : conversationFolderOf(conversation)
  if (folder && folderScopeKinds.value.includes(folder.scopeKind) && !conversationListPath.value.length) {
    conversationListPath.value = enterConversationListFolder([], folder.id)
  }
  cancelInboxRead()
  storeComposer()
  selectedContactId.value = contactId
  contactPanel.value = ''
  if (conversation.id !== selectedId.value) pendingScrollToBottomId = null
  selectedId.value = conversation.id
  restoreComposer(conversation.id)
  mobileThread.value = openMobileThread
  showInstances.value = false
  showInfoView()
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
  conversationPage.value = nextConversationPage(conversationPage.value, displayedConversations.value.length)
}

function showPreviousConversationPage() {
  conversationPage.value = previousConversationPage(conversationPage.value)
}

function selectListItem(item: Conversation, openMobileThread = true) {
  const contact = item.contactId ? snapshot.value.contacts.find((entry) => entry.id === item.contactId) : null
  if (!contact) return selectConversation(item, openMobileThread)
  const members = item.members ?? []
  const target = (selectedContactId.value === contact.id && members.find((member) => member.id === selectedId.value))
    || members.find((member) => member.id === contact.defaultConversationId) || members[0]
  return selectConversation(target, openMobileThread, contact.id)
}

function selectConversationById(conversationId: string) {
  const item = listItems.value.find((entry) => entry.id === conversationId)
  if (!item) return
  showInfoView()
  void selectListItem(item)
}

function isRowActive(row: ConversationListItem) {
  return row.contactId ? selectedContactId.value === row.contactId : !selectedContactId.value && selectedId.value === row.id
}

function selectFilter(id: string, connectorId = '') {
  conversationListPath.value = []
  activeFilter.value = id
  activeConnectorId.value = connectorId
  showInstances.value = false
  mobileThread.value = false
  showInfoView()
  applyConversationSelection(conversationListModel.value.selectionConversations)
}

function enterListFolder(folderId: string) {
  if (!canEnterConversationListFolder(conversationListPath.value)) return
  conversationListPath.value = enterConversationListFolder(conversationListPath.value, folderId)
  mobileThread.value = false
  applyConversationSelection(conversationListModel.value.selectionConversations)
}

function navigateConversationListTo(level: number) {
  const targetLength = Math.max(0, Math.min(MAX_CONVERSATION_LIST_LEVELS - 1, Math.floor(level) - 1))
  conversationListPath.value = conversationListPath.value.slice(0, targetLength)
  applyConversationSelection(conversationListModel.value.selectionConversations)
}

function applyConversationSelection(conversations: Conversation[]) {
  const selection = resolveConversationSelection(conversations, selectionKey.value)
  if (selection.action === 'select' && selection.conversation) {
    void selectListItem(selection.conversation, false)
  } else if (selection.action === 'clear') {
    storeComposer()
    pendingScrollToBottomId = null
    cancelInboxRead()
    selectedContactId.value = ''
    selectedId.value = ''
    restoreComposer('')
    snapshot.value.messages = []
    detailLoading.value = false
  }
}

function showConnectorManagement() {
  showInstances.value = true
  showFiltered.value = false
  mobileThread.value = false
}

const FILTER_RULE_LABELS: Record<string, string> = {
  link_drop: '仅含链接',
  spam_keywords: '垃圾关键词',
  custom_sender: '发件人含',
  custom_body: '正文含',
  custom_regex: '正则',
}

const FILTER_ERRORS: Record<string, string> = {
  invalid_filter_rule: '规则无效：正则有误、过长或存在回溯风险',
  invalid_filter_allowlist: '白名单无效',
}

function filterRuleLabel(message: FilteredMessage) {
  const label = FILTER_RULE_LABELS[message.rule] || '已过滤'
  return message.rule === 'link_drop' || !message.detail ? label : `${label}：${message.detail}`
}

function seedFilterDraft(settings: FilterSettings): FilterDraft {
  return {
    enabled: settings.enabled,
    linkDrop: settings.linkDrop,
    spamKeywords: settings.spamKeywords,
    customRules: settings.customRules.map((rule) => ({ ...rule })),
    allowlistText: settings.allowlist.join('\n'),
    dirty: false,
  }
}

watch(() => snapshot.value.connectors, (connectors) => {
  for (const connector of connectors) {
    const draft = filterDrafts.value[connector.id]
    if (!draft || !draft.dirty) filterDrafts.value[connector.id] = seedFilterDraft(connector.filter)
  }
}, { immediate: true })

async function saveConnectorSettings(connector: Connector, patch: { agentAccess?: AgentAccess, filter?: FilterSettings }) {
  try {
    await api(`/api/connectors/${encodeURIComponent(connector.id)}/settings`, {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(patch),
    })
    return true
  } catch (error) {
    const code = error instanceof Error ? error.message : String(error)
    notify(`保存失败：${FILTER_ERRORS[code] || code}`)
    return false
  }
}

async function setAgentAccess(connector: Connector, event: Event) {
  const agentAccess = (event.target as HTMLSelectElement).value as AgentAccess
  if (await saveConnectorSettings(connector, { agentAccess })) await refreshNow()
  else (event.target as HTMLSelectElement).value = connector.agentAccess
}

function addFilterRule(draft: FilterDraft) {
  draft.customRules.push({ type: 'body', pattern: '' })
  draft.dirty = true
}

function removeFilterRule(draft: FilterDraft, index: number) {
  draft.customRules.splice(index, 1)
  draft.dirty = true
}

async function saveFilter(connector: Connector) {
  const draft = filterDrafts.value[connector.id]
  if (!draft) return
  const filter: FilterSettings = {
    enabled: draft.enabled,
    linkDrop: draft.linkDrop,
    spamKeywords: draft.spamKeywords,
    customRules: draft.customRules
      .map((rule) => ({ type: rule.type, pattern: rule.pattern.trim() }))
      .filter((rule) => rule.pattern),
    allowlist: draft.allowlistText.split('\n').map((line) => line.trim()).filter(Boolean),
  }
  if (!await saveConnectorSettings(connector, { filter })) return
  draft.dirty = false
  notify('已保存')
  await refreshNow()
}

async function loadFiltered() {
  filteredLoading.value = true
  try {
    const body = await api<{ messages: FilteredMessage[] }>('/api/filtered')
    filteredMessages.value = body.messages
  } catch (error) {
    notify(`加载失败：${error instanceof Error ? error.message : String(error)}`)
  } finally {
    filteredLoading.value = false
  }
}

function showFilteredView() {
  showInfoView()
  showInstances.value = false
  showFiltered.value = true
  mobileThread.value = false
  void loadFiltered()
}

const CONTACT_ERRORS: Record<string, string> = {
  group_conversation_not_linkable: '群聊不能关联到联系人',
  conversation_already_linked: '该会话已关联到其他联系人',
  contact_conversation_limit: '联系人关联的会话已达上限',
  invalid_contact_name: '名称无效',
  contact_not_found: '联系人不存在',
}

const contactPanel = ref<'' | 'link' | 'manage'>('')
const linkTarget = ref('new')
const linkName = ref('')
const contactNameDraft = ref('')
const contactBusy = ref(false)
const deleteArmed = ref(false)
const suggestions = ref<ContactSuggestion[]>([])

const canLinkContact = computed(() => Boolean(selectedConversation.value)
  && !selectedContact.value && selectedConversation.value?.conversationType !== 'group')
const threadIdentity = computed(() => {
  const contact = selectedContact.value
  const conversation = selectedConversation.value
  if (!conversation) return null
  if (!contact) {
    return { title: conversation.title, label: conversation.avatarLabel || conversation.title,
      avatarPath: conversation.avatarPath, muted: Boolean(conversation.muted) }
  }
  const members = contactMembers.value
  return { title: contact.name, label: contact.name,
    avatarPath: members.find((member) => member.avatarPath)?.avatarPath ?? null,
    muted: members.length > 0 && members.every((member) => member.muted) }
})
const contactChannels = computed(() => [...new Set(contactMembers.value.map((member) => channelLabel(member)))])
const sendTargetOptions = computed(() => contactMembers.value.map((member) => ({
  id: member.id,
  label: `${channelLabel(member)} · ${connectorAccount(member.connectorId)}`,
})))
const composerName = computed(() => selectedContact.value
  ? `${selectedContact.value.name}（${channelLabel(selectedConversation.value)}）`
  : selectedConversation.value?.title ?? '')
const visibleSuggestions = computed(() => suggestions.value.flatMap((suggestion) => {
  const items = suggestion.conversationIds
    .map((id) => snapshot.value.conversations.find((item) => item.id === id))
    .filter((item): item is Conversation => Boolean(item))
  return items.length ? [{ ...suggestion, items }] : []
}))

function connectorAccount(connectorId: string) {
  return snapshot.value.connectors.find((item) => item.id === connectorId)?.accountLabel ?? ''
}

function messageChannel(message: Message) {
  const label = normalizeChannelLabel(message.channelLabel || '')
  return message.accountLabel ? `${label} · ${message.accountLabel}` : label
}

function contactErrorText(error: unknown) {
  const code = error instanceof Error ? error.message : String(error)
  return CONTACT_ERRORS[code] || code
}

function postJson(method: string, body?: unknown): RequestInit {
  return { method, headers: { 'content-type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) }
}

function openContactPanel() {
  if (contactPanel.value) {
    contactPanel.value = ''
    return
  }
  deleteArmed.value = false
  if (selectedContact.value) {
    contactNameDraft.value = selectedContact.value.name
    contactPanel.value = 'manage'
  } else {
    linkTarget.value = 'new'
    linkName.value = selectedConversation.value?.title ?? ''
    contactPanel.value = 'link'
  }
}

async function runContactAction(action: () => Promise<void>, done: string) {
  if (contactBusy.value) return
  contactBusy.value = true
  try {
    await action()
    notify(done)
    await load(selectedId.value, true, false)
  } catch (error) {
    if (!(error instanceof DOMException && error.name === 'AbortError')) notify(`操作失败：${contactErrorText(error)}`)
  } finally {
    contactBusy.value = false
  }
}

async function submitLink() {
  const conversationId = selectedId.value
  if (!conversationId) return
  await runContactAction(async () => {
    if (linkTarget.value === 'new') {
      const result = await api<{ contactId: string }>('/api/contacts',
        postJson('POST', { name: linkName.value.trim() || undefined, conversationIds: [conversationId] }))
      selectedContactId.value = result.contactId
    } else {
      await api(`/api/contacts/${encodeURIComponent(linkTarget.value)}/conversations`, postJson('POST', { conversationId }))
      selectedContactId.value = linkTarget.value
    }
    contactPanel.value = ''
  }, '已关联')
}

async function saveContactName() {
  const contact = selectedContact.value
  if (!contact) return
  await runContactAction(async () => {
    await api(`/api/contacts/${encodeURIComponent(contact.id)}`, postJson('PUT', { name: contactNameDraft.value }))
  }, '已保存')
}

async function unlinkConversation(conversationId: string) {
  const contact = selectedContact.value
  if (!contact) return
  await runContactAction(async () => {
    await api(`/api/contacts/${encodeURIComponent(contact.id)}/conversations/${encodeURIComponent(conversationId)}`,
      postJson('DELETE'))
  }, '已取消关联')
}

async function deleteContact() {
  const contact = selectedContact.value
  if (!contact) return
  if (!deleteArmed.value) {
    deleteArmed.value = true
    return
  }
  await runContactAction(async () => {
    await api(`/api/contacts/${encodeURIComponent(contact.id)}`, postJson('DELETE'))
    contactPanel.value = ''
  }, '已删除联系人，消息不受影响')
}

function chooseSendTarget(conversationId: string) {
  if (!selectedContactId.value || conversationId === selectedId.value) return
  const carried = draft.value
  draft.value = ''
  storeComposer()
  selectedId.value = conversationId
  restoreComposer(conversationId)
  if (carried && !draft.value) draft.value = carried
  void load(conversationId, true).catch(() => {})
}

async function loadSuggestions() {
  try {
    suggestions.value = (await api<{ suggestions: ContactSuggestion[] }>('/api/contacts/suggestions')).suggestions
  } catch {
    suggestions.value = []
  }
}

async function confirmSuggestion(suggestion: ContactSuggestion) {
  await runContactAction(async () => {
    if (suggestion.contactId) {
      for (const conversationId of suggestion.conversationIds) {
        await api(`/api/contacts/${encodeURIComponent(suggestion.contactId)}/conversations`,
          postJson('POST', { conversationId }))
      }
    } else {
      await api('/api/contacts', postJson('POST', { name: suggestion.name, conversationIds: suggestion.conversationIds }))
    }
  }, '已关联')
}

async function dismissSuggestion(suggestion: ContactSuggestion) {
  suggestions.value = suggestions.value.filter((item) => item.key !== suggestion.key)
  try {
    await api('/api/contacts/suggestions/dismiss', postJson('POST', { key: suggestion.key }))
  } catch (error) {
    notify(`操作失败：${contactErrorText(error)}`)
    void loadSuggestions()
  }
}

watch(
  () => `${snapshot.value.conversations.length}:${snapshot.value.contacts.map((item) => `${item.id}${item.conversationIds.length}`).join(',')}`,
  () => { void loadSuggestions() },
)

const fetchingMessageIds = ref(new Set<string>())

function canFetchMedia(message: Message, kind: string) {
  const conversation = selectedConversation.value
  if (message.direction !== 'inbound' || message.attachments.length || !conversation) return false
  if (!['image', 'sticker', 'file'].includes(kind)) return false
  if (selectedConversationConnector.value?.mode !== 'device_relay' || !connectorReachable.value) return false
  return conversation.capabilities.includes(kind === 'file' ? 'receive_files' : 'receive_images')
}

async function fetchMedia(message: Message) {
  fetchingMessageIds.value = new Set([...fetchingMessageIds.value, message.id])
  try {
    await api(`/api/messages/${encodeURIComponent(message.id)}/fetch-media`, { method: 'POST' })
    notify('已请求取回，完成后会出现在这条消息下')
    // A failed fetch leaves no trace in the thread, so the button comes back after the adapter's time limit.
    window.setTimeout(() => {
      const next = new Set(fetchingMessageIds.value)
      next.delete(message.id)
      fetchingMessageIds.value = next
    }, 200_000)
  } catch (error) {
    const code = error instanceof Error ? error.message : String(error)
    notify(code === 'media_not_latest' ? '只能取回这个会话里最新的一条同类消息' : `取回失败：${code}`)
    const next = new Set(fetchingMessageIds.value)
    next.delete(message.id)
    fetchingMessageIds.value = next
  }
}

async function restoreFiltered(message: FilteredMessage, allowlist: boolean) {
  try {
    await api(`/api/messages/${encodeURIComponent(message.id)}/restore`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ allowlist }),
    })
    filteredMessages.value = filteredMessages.value.filter((item) => item.id !== message.id)
    notify(allowlist ? '已恢复并加入白名单' : '已恢复')
    await refreshNow()
  } catch (error) {
    notify(`恢复失败：${error instanceof Error ? error.message : String(error)}`)
  }
}

watch(() => snapshot.value.filteredCount, () => {
  if (showFiltered.value) void loadFiltered()
})

const VIEW_MODE_KEY = 'message-center:view-mode'
const NATIVE_DESKTOP_KEY = 'message-center:native-desktop'

function readStored(key: string) {
  try {
    return localStorage.getItem(key) || ''
  } catch {
    return ''
  }
}

function writeStored(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch { /* storage unavailable */ }
}

const viewMode = ref<'info' | 'native'>(readStored(VIEW_MODE_KEY) === 'native' ? 'native' : 'info')
const nativeDesktopKey = ref(readStored(NATIVE_DESKTOP_KEY))

function showInfoView() {
  viewMode.value = 'info'
  showFiltered.value = false
  writeStored(VIEW_MODE_KEY, 'info')
}

function showNativeView(connector?: Connector | null) {
  if (connector) {
    nativeDesktopKey.value = connector.nativeDesktop || connector.id
    writeStored(NATIVE_DESKTOP_KEY, nativeDesktopKey.value)
  }
  viewMode.value = 'native'
  writeStored(VIEW_MODE_KEY, 'native')
  showInstances.value = false
  showFiltered.value = false
  mobileThread.value = false
}

function selectNativeDesktop(key: string) {
  nativeDesktopKey.value = key
  writeStored(NATIVE_DESKTOP_KEY, key)
}

async function uploadFiles(event: Event) {
  const input = event.currentTarget as HTMLInputElement
  await stageFiles(Array.from(input.files || []))
  input.value = ''
}

async function stageFiles(selectedFiles: File[]) {
  const targetConversationId = selectedId.value
  const targetCapabilities = [...(selectedConversation.value?.capabilities ?? [])]
  const targetDeviceConversation = selectedConversationConnector.value?.mode === 'device_relay'
  if (!targetConversationId || uploadingConversationIds.value.has(targetConversationId)) return
  if (targetDeviceConversation && staged.value.length + selectedFiles.length > 1) {
    notify('设备接入请每次单独发送一个附件')
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
  }
}

type Sticker = { id: string, fileName: string, mimeType: string, sizeBytes: number, sha256: string, path: string }
type StickerPack = { id: string, name: string, images: Sticker[] }
const stickerOpen = ref(false)
const stickers = ref<Sticker[] | null>(null)
const stickerPacks = ref<StickerPack[]>([])
const stickerTab = ref('recent')
const stickersLoading = ref(false)
const stickersFailed = ref(false)
const stickerPicker = ref<HTMLElement | null>(null)
const canSendImages = computed(() => canSendFiles.value && supportsAttachment(
  selectedConversation.value?.capabilities ?? [], 'image/gif', 'sticker.gif',
))
const visibleStickers = computed(() => stickerTab.value === 'recent'
  ? stickers.value ?? []
  : stickerPacks.value.find((pack) => pack.id === stickerTab.value)?.images ?? [])

function withPath(sticker: Omit<Sticker, 'path'>, base: string): Sticker {
  return { ...sticker, path: `${base}/${encodeURIComponent(sticker.id)}` }
}

async function loadStickerPacks() {
  const { packs } = await api<{ packs: StickerPack[] }>('/api/sticker-packs')
  stickerPacks.value = packs.map((pack) => ({
    ...pack, images: pack.images.map((image) => withPath(image, '/api/sticker-images')),
  }))
  if (stickerTab.value !== 'recent' && !stickerPacks.value.some((pack) => pack.id === stickerTab.value)) {
    stickerTab.value = 'recent'
  }
}

async function loadStickers() {
  stickersLoading.value = true
  stickersFailed.value = false
  try {
    const [recent] = await Promise.all([api<{ stickers: Omit<Sticker, 'path'>[] }>('/api/stickers'), loadStickerPacks()])
    stickers.value = recent.stickers.map((sticker) => withPath(sticker, '/api/files'))
  } catch {
    stickersFailed.value = true
  } finally {
    stickersLoading.value = false
  }
}

function toggleStickers() {
  stickerOpen.value = !stickerOpen.value
  if (stickerOpen.value && (stickers.value === null || stickersFailed.value) && !stickersLoading.value) void loadStickers()
}

async function pickSticker(sticker: Sticker) {
  stickerOpen.value = false
  try {
    const response = await fetch(sticker.path, { credentials: 'same-origin' })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const blob = await response.blob()
    await stageFiles([new File([blob], sticker.fileName, { type: sticker.mimeType })])
  } catch (error) {
    notify(`表情加载失败：${error instanceof Error ? error.message : String(error)}`)
  }
}

const packManageOpen = ref(false)
const packBusy = ref(false)
const managedPackId = ref('')
const newPackName = ref('')
const renamedPackName = ref('')
const managedPack = computed(() => stickerPacks.value.find((pack) => pack.id === managedPackId.value) ?? null)

function openPackManager() {
  stickerOpen.value = false
  packManageOpen.value = true
  if (!managedPack.value) managedPackId.value = stickerPacks.value[0]?.id ?? ''
  renamedPackName.value = managedPack.value?.name ?? ''
}

function selectManagedPack(id: string) {
  managedPackId.value = id
  renamedPackName.value = managedPack.value?.name ?? ''
}

async function runPackAction(action: () => Promise<void>, failure: string) {
  packBusy.value = true
  try {
    await action()
    await loadStickerPacks()
  } catch (error) {
    notify(`${failure}：${error instanceof Error ? error.message : String(error)}`)
  } finally {
    packBusy.value = false
  }
}

const packJson = (method: string, body: unknown): RequestInit => ({
  method, headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
})

async function createStickerPack() {
  const name = newPackName.value.trim()
  if (!name) return
  await runPackAction(async () => {
    const { pack } = await api<{ pack: StickerPack }>('/api/sticker-packs', packJson('POST', { name }))
    newPackName.value = ''
    managedPackId.value = pack.id
    renamedPackName.value = pack.name
  }, '新建失败')
}

async function renameStickerPack() {
  const pack = managedPack.value
  const name = renamedPackName.value.trim()
  if (!pack || !name || name === pack.name) return
  await runPackAction(async () => {
    await api(`/api/sticker-packs/${pack.id}`, packJson('PUT', { name }))
  }, '重命名失败')
}

async function deleteStickerPack() {
  const pack = managedPack.value
  if (!pack || !window.confirm(`删除表情包“${pack.name}”及其中 ${pack.images.length} 张图片？删除后无法恢复。`)) return
  await runPackAction(async () => {
    await api(`/api/sticker-packs/${pack.id}`, { method: 'DELETE' })
    managedPackId.value = stickerPacks.value.find((item) => item.id !== pack.id)?.id ?? ''
    renamedPackName.value = stickerPacks.value.find((item) => item.id === managedPackId.value)?.name ?? ''
  }, '删除失败')
}

async function moveStickerPack(id: string, offset: number) {
  const ids = stickerPacks.value.map((pack) => pack.id)
  const from = ids.indexOf(id)
  const to = from + offset
  if (from < 0 || to < 0 || to >= ids.length) return
  ids.splice(to, 0, ...ids.splice(from, 1))
  await runPackAction(async () => {
    await api('/api/sticker-packs/order', packJson('PUT', { ids }))
  }, '排序失败')
}

async function addPackImages(event: Event) {
  const input = event.target as HTMLInputElement
  const files = [...(input.files ?? [])]
  input.value = ''
  const pack = managedPack.value
  if (!pack || !files.length) return
  await runPackAction(async () => {
    for (const file of files) {
      const form = new FormData()
      form.append('file', file)
      await api(`/api/sticker-packs/${pack.id}/images`, { method: 'POST', body: form })
    }
  }, '添加失败')
}

async function collectSticker(sticker: Sticker) {
  const pack = managedPack.value
  if (!pack) return
  await runPackAction(async () => {
    await api(`/api/sticker-packs/${pack.id}/images/from-attachment`, packJson('POST', { attachmentId: sticker.id }))
  }, '添加失败')
}

async function removePackImage(image: Sticker) {
  const pack = managedPack.value
  if (!pack) return
  await runPackAction(async () => {
    await api(`/api/sticker-packs/${pack.id}/images/${image.id}`, { method: 'DELETE' })
  }, '移除失败')
}

function onStickerPointer(event: PointerEvent) {
  if (stickerOpen.value && !stickerPicker.value?.contains(event.target as Node)) stickerOpen.value = false
}

function onStickerKeydown(event: KeyboardEvent) {
  if (event.key !== 'Escape' || !stickerOpen.value) return
  stickerOpen.value = false
  stickerPicker.value?.querySelector<HTMLElement>('.sticker-toggle')?.focus()
}

function onPackDialogKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && packManageOpen.value) packManageOpen.value = false
}

watch(selectedId, () => { stickerOpen.value = false })
watch(canSendImages, (value) => { if (!value) { stickerOpen.value = false; packManageOpen.value = false } })

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
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js', { scope: '/' }).then(refreshPush, () => {})
  }
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
  liveSignal.start()
  clockTimer = window.setInterval(() => { nowTick.value = Date.now() }, 60_000)
  window.addEventListener('pageshow', onPageShow)
  document.addEventListener('pointerdown', onStickerPointer)
  document.addEventListener('keydown', onStickerKeydown)
  document.addEventListener('keydown', onPackDialogKeydown)
  window.addEventListener('pagehide', onOffline)
  window.addEventListener('online', onOnline)
  window.addEventListener('offline', onOffline)
  document.addEventListener('visibilitychange', onVisibilityChange)
})

onUnmounted(() => {
  document.removeEventListener('pointerdown', onStickerPointer)
  document.removeEventListener('keydown', onStickerKeydown)
  document.removeEventListener('keydown', onPackDialogKeydown)
  refreshLoop?.stop()
  liveSignal.stop()
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
  <main class="mc-shell" :class="{ 'is-thread-open': mobileThread, 'is-instances-open': overlayPane }">
    <aside class="nav-pane" aria-label="导航">
      <div class="brand">
        <span class="brand-mark" aria-hidden="true"><AppIcon name="brand" :size="18" /></span>
        <span class="brand-copy">
          <strong>Message Center</strong>
          <small><span class="presence-dot" :class="onlineConnectorCount ? 'online' : degradedConnectorCount ? 'degraded' : 'offline'" />{{ onlineConnectorCount }} 在线<span v-if="degradedConnectorCount"> · {{ degradedConnectorCount }} 部分同步</span><span v-if="snapshot.connectors.length"> / {{ snapshot.connectors.length }} 接入</span></small>
        </span>
      </div>

      <div v-if="nativeDesktops.length" class="view-switch" role="group" aria-label="视图">
        <button type="button" :class="{ active: !nativeViewActive }" :aria-pressed="!nativeViewActive" @click="showInfoView(); showInstances = false">信息</button>
        <button type="button" :class="{ active: nativeViewActive }" :aria-pressed="nativeViewActive" @click="showNativeView()">原生</button>
      </div>

      <nav class="nav-scroll" aria-label="收件箱分类">
        <div class="nav-section">
          <p class="nav-label">{{ nativeViewActive ? '原生桌面' : '收件箱' }}</p>
          <template v-if="nativeViewActive">
            <button class="nav-item is-disabled" type="button" aria-disabled="true" title="切换到信息视图后可查看全部会话">
              <span class="nav-glyph is-all" aria-hidden="true"><AppIcon name="inbox" :size="16" /></span>
              <span class="nav-copy">全部</span>
            </button>
            <button
              v-for="desktop in nativeDesktops"
              :key="desktop.key"
              class="nav-item"
              :class="{ active: desktop.key === activeNativeDesktop?.key }"
              type="button"
              :title="desktop.label"
              :aria-current="desktop.key === activeNativeDesktop?.key ? 'page' : undefined"
              @click="selectNativeDesktop(desktop.key)"
            >
              <span
                class="nav-glyph channel-tone"
                :class="`tone-${channelTone(desktop.channel)}`"
                :data-unread="desktop.unread > 0 || undefined"
                aria-hidden="true"
              >
                <AppIcon v-if="channelIcon(desktop.channel)" :name="channelIcon(desktop.channel)!" :size="16" />
                <template v-else>{{ channelGlyph(desktop.channel) }}</template>
              </span>
              <span class="nav-copy">{{ desktop.label }}</span>
              <span v-if="desktop.unread" class="nav-count is-unread" aria-hidden="true">{{ desktop.unread > 99 ? '99+' : desktop.unread }}</span>
              <span v-if="desktop.unread" class="sr-only">，{{ desktop.unread }} 条未读</span>
            </button>
          </template>
          <button
            v-for="filter in nativeViewActive ? [] : filters"
            :key="filter.id"
            class="nav-item"
            :class="{ active: activeFilter === filter.id && !overlayPane && !nativeViewActive }"
            type="button"
            :title="filter.label"
            :aria-current="activeFilter === filter.id && !overlayPane && !nativeViewActive ? 'page' : undefined"
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
              <AppIcon v-else-if="channelIcon(filter.channel)" :name="channelIcon(filter.channel)!" :size="16" />
              <template v-else>{{ channelGlyph(filter.channel) }}</template>
            </span>
            <span class="nav-copy">{{ filter.label }}</span>
            <span v-if="filter.unread" class="nav-count is-unread" aria-hidden="true">{{ filter.unread > 99 ? '99+' : filter.unread }}</span>
            <span v-else class="nav-count" aria-hidden="true">{{ filter.count }}</span>
            <span class="sr-only">，{{ filter.count }} 个会话，{{ filter.unread }} 条未读</span>
          </button>
          <button
            class="nav-item"
            :class="{ active: showFiltered }"
            type="button"
            title="已过滤"
            :aria-current="showFiltered ? 'page' : undefined"
            @click="showFilteredView"
          >
            <span class="nav-glyph is-system" aria-hidden="true"><AppIcon name="filter" :size="16" /></span>
            <span class="nav-copy">已过滤</span>
            <span class="nav-count" aria-hidden="true">{{ snapshot.filteredCount }}</span>
            <span class="sr-only">，{{ snapshot.filteredCount }} 条</span>
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
            >{{ onlineConnectorCount + degradedConnectorCount }}/{{ snapshot.connectors.length }}</span>
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

    <section v-if="nativeViewActive && !overlayPane" class="native-pane" aria-label="原生桌面">
      <header class="thread-header native-header">
        <h1 class="native-title">{{ activeNativeDesktop?.label }}</h1>
        <a v-if="activeNativeDesktop" class="native-open-link" :href="activeNativeDesktop.src" target="_blank" rel="noopener noreferrer">在新窗口打开</a>
      </header>
      <iframe
        v-if="activeNativeDesktop"
        :key="activeNativeDesktop.key"
        class="native-frame"
        :src="activeNativeDesktop.src"
        :title="`${activeNativeDesktop.label} 原生桌面`"
        allow="clipboard-read; clipboard-write; autoplay; fullscreen"
        referrerpolicy="no-referrer"
      />
    </section>

    <section v-if="!overlayPane && !nativeViewActive" class="conversation-pane" aria-label="会话列表">
      <header class="pane-header">
        <div class="pane-title">
          <h1>{{ conversationListTitle }}</h1>
          <nav v-if="conversationListPath.length" class="conversation-breadcrumb" aria-label="会话列表路径">
            <template v-for="(crumb, index) in conversationListBreadcrumbs" :key="`${index}:${crumb}`">
              <button
                v-if="index < conversationListBreadcrumbs.length - 1"
                type="button"
                :aria-label="`返回${crumb}列表`"
                @click="navigateConversationListTo(index + 1)"
              >{{ crumb }}</button>
              <span v-else aria-current="page">{{ crumb }}</span>
              <AppIcon v-if="index < conversationListBreadcrumbs.length - 1" name="arrowRight" :size="12" aria-hidden="true" />
            </template>
          </nav>
          <p aria-live="polite">
            {{ displayedConversationCount }} 个会话<template v-if="displayedUnread"> · <strong>{{ displayedUnread }}</strong> 条未读</template>
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
            >未读<span v-if="displayedUnread" class="segmented-dot" aria-hidden="true" /></button>
          </div>
        </div>

        <details v-if="visibleSuggestions.length && !conversationListPath.length" class="contact-suggestions">
          <summary>可能是同一人 <span class="suggestion-count">{{ visibleSuggestions.length }}</span></summary>
          <ul>
            <li v-for="suggestion in visibleSuggestions" :key="suggestion.key" :data-suggestion-key="suggestion.key">
              <span class="suggestion-copy">
                <strong>{{ suggestion.name }}</strong>
                <small>{{ suggestion.items.map((item) => `${channelLabel(item)} · ${connectorAccount(item.connectorId)}`).join('、') }}<template v-if="suggestion.contactId">，加入已有联系人</template></small>
              </span>
              <button type="button" class="suggestion-action" :disabled="contactBusy" @click="confirmSuggestion(suggestion)">关联</button>
              <button type="button" class="suggestion-action quiet" @click="dismissSuggestion(suggestion)">忽略</button>
            </li>
          </ul>
        </details>

        <ul class="conversation-items">
          <li v-for="listFolder in listFolders" :key="listFolder.id">
            <button
              class="conversation-row conversation-folder-row"
              :class="{ active: listFolder.active, unread: listFolder.unreadCount > 0 }"
              type="button"
              :aria-label="`${listFolder.title}，${listFolder.count} ${getConversationFolder(listFolder.id)?.unit ?? ''}，${listFolder.unreadCount} 条未读`"
              :aria-current="listFolder.active ? 'true' : undefined"
              :data-list-folder="listFolder.id"
              :data-folder-count="listFolder.count"
              :data-unread-count="listFolder.unreadCount"
              @click="enterListFolder(listFolder.id)"
            >
              <span class="avatar conversation-avatar folder-avatar" aria-hidden="true">
                <AppIcon name="group" :size="18" />
              </span>
              <span class="conversation-copy">
                <span class="conversation-title-row">
                  <strong><span class="conversation-title">{{ listFolder.title }}</span></strong>
                  <AppIcon name="arrowRight" :size="14" aria-hidden="true" />
                </span>
                <span class="conversation-meta-row">
                  <span class="conversation-preview">{{ listFolder.count }} {{ getConversationFolder(listFolder.id)?.unit }}</span>
                  <span v-if="listFolder.unreadCount" class="unread-count" aria-hidden="true">
                    {{ listFolder.unreadCount > 99 ? '99+' : listFolder.unreadCount }}
                  </span>
                </span>
              </span>
            </button>
          </li>
          <li v-for="conversation in conversationRows" :key="conversation.id">
            <button
              class="conversation-row"
              :class="{
                active: isRowActive(conversation),
                pinned: conversation.pinned,
                folded: isFolded(conversation),
                unread: conversation.unreadCount > 0,
                muted: conversation.muted,
              }"
              type="button"
              :aria-current="isRowActive(conversation) ? 'true' : undefined"
              :data-conversation-id="conversation.id"
              :data-contact-id="conversation.contactId || undefined"
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
                  v-if="activeFilter === 'all' && !activeConnectorId && !conversation.contactId"
                  class="channel-badge channel-tone"
                  :class="`tone-${channelTone(conversation.channel)}`"
                  aria-hidden="true"
                ><AppIcon v-if="channelIcon(conversation.channel)" :name="channelIcon(conversation.channel)!" :size="12" /><template v-else>{{ channelGlyph(conversation.channel) }}</template></span>
              </span>
              <span class="conversation-copy">
                <span class="conversation-title-row">
                  <strong>
                    <AppIcon v-if="conversation.conversationType === 'group'" class="title-icon" name="group" :size="14" />
                    <AppIcon v-if="isFolded(conversation)" class="title-icon" name="archive" :size="14" />
                    <span class="conversation-title">{{ conversation.title }}</span>
                  </strong>
                  <span v-if="conversation.channels.length" class="contact-channels" aria-hidden="true">
                    <span
                      v-for="label in conversation.channels"
                      :key="label"
                      class="contact-channel channel-tone"
                      :class="`tone-${channelTone(label)}`"
                      :title="label"
                    ><AppIcon v-if="channelIcon(label)" :name="channelIcon(label)!" :size="11" /><template v-else>{{ channelGlyph(label) }}</template></span>
                  </span>
                  <AppIcon v-if="conversation.pinned" class="pin-icon" name="pin" :size="12" />
                  <span v-if="conversation.muted" class="muted-icon" role="img" aria-label="免打扰"><AppIcon name="bellOff" :size="13" /></span>
                  <time
                    :datetime="isoTime(conversation.lastMessageAt)"
                    :title="formatFullStamp(conversation.lastMessageAt)"
                  >{{ listTime(conversation.lastMessageAt) }}</time>
                </span>
                <span class="conversation-meta-row">
                  <span class="conversation-preview">{{ conversationPreview(conversation) }}</span>
                  <span v-if="conversation.unreadCount" class="unread-count" aria-hidden="true">{{ conversation.unreadCount > 99 ? '99+' : conversation.unreadCount }}</span>
                </span>
                <span class="sr-only">，<template v-if="conversation.channels.length">联系人，{{ conversation.channels.join('、') }}</template><template v-else>{{ conversation.channel }}</template><template v-if="conversationStateText(conversation)">，{{ conversationStateText(conversation) }}</template></span>
              </span>
            </button>
          </li>
        </ul>

        <div v-if="totalConversationPages > 1" class="conversation-pager">
          <FluentButton type="button" :disabled="conversationPage === 0" @click="showPreviousConversationPage">上一页</FluentButton>
          <span>{{ conversationRangeStart }}–{{ conversationRangeEnd }} / {{ displayedConversations.length }}</span>
          <FluentButton
            type="button"
            :disabled="conversationPage >= totalConversationPages - 1"
            @click="showNextConversationPage"
          >下一页</FluentButton>
        </div>
        <div v-if="!displayedConversations.length && !loading" class="empty-state">
          <span class="empty-glyph"><AppIcon :name="unreadOnly ? 'unread' : 'chat'" :size="22" /></span>
          <p>{{ conversationSearch.trim() ? '没有匹配的会话' : unreadOnly ? '没有未读会话' : '暂无会话' }}</p>
        </div>
        <div v-if="loading" class="loading-state"><span class="spinner" />正在载入</div>
      </div>
    </section>

    <section v-if="!overlayPane && !nativeViewActive" class="content-pane" aria-label="会话详情">
      <template v-if="selectedConversation && threadIdentity">
        <header class="thread-header">
          <button class="quiet-button mobile-back" type="button" aria-label="返回收件箱" title="返回收件箱" @click="mobileThread = false">
            <AppIcon name="back" :size="18" />
          </button>
          <span class="avatar thread-avatar" :class="`avatar-tone-${avatarTone(threadIdentity.title)}`">
            <span aria-hidden="true">{{ initials(threadIdentity.label) }}</span>
            <img
              v-if="threadIdentity.avatarPath"
              :key="avatarKey(threadIdentity.avatarPath)"
              :src="avatarSource(threadIdentity.avatarPath)"
              :data-avatar-path="threadIdentity.avatarPath"
              :data-avatar-revision="avatarRevision(threadIdentity.avatarPath)"
              alt=""
              @load="imageLoaded"
              @error="imageFailed"
            >
          </span>
          <div class="thread-title">
            <h2>{{ threadIdentity.title }}<span v-if="threadIdentity.muted" class="muted-icon" role="img" aria-label="免打扰"><AppIcon name="bellOff" :size="14" /></span></h2>
            <p v-if="selectedContact" class="thread-subtitle">
              <span>联系人</span>
              <span
                v-for="label in contactChannels"
                :key="label"
                class="channel-tag channel-tone"
                :class="`tone-${channelTone(label)}`"
              >{{ label }}</span>
            </p>
            <p v-else class="thread-subtitle">
              <span class="channel-tag channel-tone" :class="`tone-${channelTone(channelLabel(selectedConversation))}`">{{ channelLabel(selectedConversation) }}</span>
              <span v-if="selectedConversation.conversationType === 'group'">群聊</span>
              <span v-else-if="selectedConversation.conversationType === 'direct'">私聊</span>
              <span class="presence" :class="selectedConversation.connectorState">
                <span class="presence-dot" :class="selectedConversation.connectorState" />接入{{ statusLabel(selectedConversation.connectorState) }}
              </span>
            </p>
          </div>
          <button
            v-if="canLinkContact || selectedContact"
            type="button"
            class="header-text-button"
            :aria-expanded="contactPanel !== ''"
            @click="openContactPanel"
          >{{ selectedContact ? '管理联系人' : '关联联系人' }}</button>
          <div v-if="selectedConversationConnector?.native" class="segmented" role="group" aria-label="显示模式">
            <button type="button" class="active" aria-pressed="true">信息模式</button>
            <button type="button" aria-pressed="false" @click="showNativeView(selectedConversationConnector)">原生模式</button>
          </div>
          <span v-if="aiUnreadCount" class="status-chip ai-unread-chip" :title="`AI 未读 ${aiUnreadCount} 条`">
            <span class="unread-dot" /><span class="chip-label">AI 未读</span> {{ aiUnreadCount }}
          </span>
        </header>

        <section v-if="contactPanel" class="contact-panel" aria-label="联系人">
          <template v-if="contactPanel === 'link'">
            <label class="panel-field">
              <span>关联到</span>
              <select v-model="linkTarget">
                <option value="new">新建联系人</option>
                <option v-for="contact in snapshot.contacts" :key="contact.id" :value="contact.id">{{ contact.name }}</option>
              </select>
            </label>
            <label v-if="linkTarget === 'new'" class="panel-field">
              <span>名称</span>
              <input v-model="linkName" type="text" maxlength="100" @keydown.enter.prevent="submitLink">
            </label>
            <div class="panel-actions">
              <button type="button" class="panel-button" @click="contactPanel = ''">取消</button>
              <button type="button" class="panel-button primary" :disabled="contactBusy" @click="submitLink">关联</button>
            </div>
          </template>
          <template v-else-if="selectedContact">
            <label class="panel-field">
              <span>名称</span>
              <input v-model="contactNameDraft" type="text" maxlength="100" @keydown.enter.prevent="saveContactName">
              <button
                type="button"
                class="panel-button"
                :disabled="contactBusy || !contactNameDraft.trim() || contactNameDraft.trim() === selectedContact.name"
                @click="saveContactName"
              >保存</button>
            </label>
            <ul class="panel-links">
              <li v-for="member in contactMembers" :key="member.id">
                <span class="channel-tag channel-tone" :class="`tone-${channelTone(channelLabel(member))}`">{{ channelLabel(member) }}</span>
                <span class="panel-link-name">{{ connectorAccount(member.connectorId) }} · {{ member.title }}</span>
                <button
                  type="button"
                  class="panel-button"
                  :disabled="contactBusy || contactMembers.length < 2"
                  :title="contactMembers.length < 2 ? '至少保留一个会话，或删除联系人' : undefined"
                  @click="unlinkConversation(member.id)"
                >取消关联</button>
              </li>
            </ul>
            <div class="panel-actions">
              <button type="button" class="panel-button danger" :disabled="contactBusy" @click="deleteContact">{{ deleteArmed ? '确认删除（不删除消息）' : '删除联系人' }}</button>
              <button type="button" class="panel-button" @click="contactPanel = ''">关闭</button>
            </div>
          </template>
        </section>

        <div class="message-scroll" :class="{ busy: detailLoading }" role="log" aria-label="消息记录" :aria-busy="detailLoading">
          <template v-for="entry in threadRows" :key="entry.key">
            <div v-if="entry.kind === 'day'" class="day-divider">
              <time :datetime="entry.dateTime">{{ entry.label }}</time>
            </div>
            <article
              v-else-if="entry.systemText"
              :data-message-id="entry.message.id"
              :data-presentation="entry.systemPresentation || undefined"
              class="message-row system"
              :data-direction="entry.message.direction"
              :data-ai-read="entry.aiRead === null ? undefined : String(entry.aiRead)"
            >
              <p class="system-notice" :data-block="entry.systemPresentation === 'system' ? 'system' : 'notice'">
                <AppIcon v-if="entry.systemPresentation !== 'system'" name="handWave" :size="14" />{{ entry.systemText }}
                <time class="sr-only" :datetime="isoTime(entry.message.occurredAt)">{{ formatFullStamp(entry.message.occurredAt) }}</time>
              </p>
            </article>
            <article
              v-else
              :data-message-id="entry.message.id"
              class="message-row"
              :class="[entry.message.direction, { continuation: entry.continuation, 'by-agent': entry.byAgent }]"
              :data-direction="entry.message.direction"
              :data-author-role="entry.message.authorRole || undefined"
              :data-delivery-state="entry.message.direction === 'outbound' ? entry.message.deliveryState || undefined : undefined"
              :data-ai-read="entry.aiRead === null ? undefined : String(entry.aiRead)"
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
                  <span
                    v-if="selectedContact && entry.message.channelLabel"
                    class="message-channel channel-tone"
                    :class="`tone-${channelTone(normalizeChannelLabel(entry.message.channelLabel))}`"
                    :data-conversation-id="entry.message.conversationId"
                  >{{ messageChannel(entry.message) }}</span>
                  <time
                    :datetime="isoTime(entry.message.occurredAt)"
                    :title="formatFullStamp(entry.message.occurredAt)"
                  >{{ formatClock(entry.message.occurredAt) }}</time>
                </p>
                <div
                  class="message-bubble"
                  :class="{ bare: entry.bare }"
                  :title="entry.continuation ? formatFullStamp(entry.message.occurredAt) : undefined"
                >
                  <blockquote v-if="entry.message.reply" class="block-quote" data-block="reply-quote">
                    <AppIcon class="quote-icon" name="quote" :size="14" />
                    <span class="quote-copy">
                      <span class="quote-author">引用内容</span>
                      <span class="quote-text">
                        <template v-if="entry.message.reply.sourceExpired">原消息内容已失效</template>
                        <template v-else>
                          {{ entry.message.reply.sourceText || '引用了一条消息' }}<template v-if="entry.message.reply.sourceTextTruncated">…</template>
                        </template>
                      </span>
                    </span>
                  </blockquote>
                  <template v-for="(block, blockIndex) in entry.blocks" :key="blockIndex">
                    <p v-if="block.type === 'text'" class="block-text">{{ block.text }}</p>
                    <blockquote v-else-if="block.type === 'quote'" class="block-quote" data-block="quote">
                      <AppIcon class="quote-icon" name="quote" :size="14" />
                      <span class="quote-copy">
                        <span v-if="block.author" class="quote-author">{{ block.author }}</span>
                        <span class="quote-text">{{ block.text || '引用了一条消息' }}</span>
                      </span>
                    </blockquote>
                    <div v-else-if="block.type === 'card'" class="block-card" :class="`card-${block.kind}`" data-block="card" :data-card-kind="block.kind">
                      <span v-if="block.source" class="card-source"><AppIcon :name="CARD_ICONS[block.kind]" :size="14" />{{ block.source }}</span>
                      <strong class="card-title">{{ block.title || block.label }}</strong>
                      <span v-if="block.summary" class="card-summary">{{ block.summary }}</span>
                      <span class="card-type"><AppIcon :name="CARD_ICONS[block.kind]" :size="12" />{{ block.label }}</span>
                    </div>
                    <div v-else-if="block.type === 'money'" class="block-money" :class="`money-${block.kind}`" data-block="money" :data-money-kind="block.kind">
                      <span class="money-main">
                        <span class="money-icon"><AppIcon :name="MONEY_ICONS[block.kind]" :size="18" /></span>
                        <span class="money-copy">
                          <strong>{{ block.amount || block.summary || block.label }}</strong>
                          <small v-if="block.amount && block.summary">{{ block.summary }}</small>
                        </span>
                      </span>
                      <span class="money-foot">{{ block.label }}<template v-if="block.status"> · {{ block.status }}</template></span>
                    </div>
                    <p v-else-if="block.type === 'notice'" class="block-notice" data-block="notice"><AppIcon name="handWave" :size="14" />{{ block.text }}</p>
                    <span v-else class="block-media" data-block="media" :data-media-kind="block.kind">
                      <AppIcon :name="MEDIA_ICONS[block.kind]" :size="14" />{{ block.label }}
                      <button
                        v-if="canFetchMedia(entry.message, block.kind)"
                        type="button"
                        class="media-fetch"
                        :disabled="fetchingMessageIds.has(entry.message.id)"
                        title="打开原会话取回内容，会把该会话标为已读"
                        @click="fetchMedia(entry.message)"
                      >{{ fetchingMessageIds.has(entry.message.id) ? '取回中' : '取回' }}</button>
                    </span>
                  </template>
                  <div v-for="file in entry.message.attachments" :key="file.id" class="attachment">
                    <img
                      v-if="isImage(file)"
                      class="attachment-image"
                      :class="{ 'attachment-image-sticker': isSticker(file) }"
                      :src="filePath(file)"
                      :alt="isSticker(file) ? 'QQ 表情' : file.fileName"
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
                      <span class="file-copy"><strong>{{ file.presentation === 'sticker' ? 'QQ 表情' : file.fileName }}</strong><small>等待上传</small></span>
                    </span>
                  </div>
                </div>
                <p v-if="entry.delivery || entry.aiRead !== null" class="message-status">
                  <span v-if="entry.delivery" class="message-delivery-state" :class="`tone-${entry.delivery.tone}`"><AppIcon :name="entry.delivery.icon" :size="12" />{{ entry.delivery.label }}</span>
                  <span v-if="entry.aiRead !== null" class="message-ai-read" :class="entry.aiRead ? 'is-read' : 'is-unread'"><AppIcon v-if="entry.aiRead" name="eye" :size="12" /><span v-else class="unread-dot" />{{ entry.aiRead ? 'AI 已读' : 'AI 未读' }}</span>
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
              :placeholder="canSendText ? `回复 ${composerName}` : '此接入仅接收消息'"
              :aria-label="`回复 ${composerName}`"
              rows="2"
              @keydown="onComposerKeydown"
            />
            <div class="compose-toolbar">
              <label v-if="selectedContact && sendTargetOptions.length > 1" class="send-target">
                <span class="sr-only">发送渠道</span>
                <select :value="selectedId" @change="chooseSendTarget(($event.target as HTMLSelectElement).value)">
                  <option v-for="option in sendTargetOptions" :key="option.id" :value="option.id">{{ option.label }}</option>
                </select>
              </label>
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
              <div v-if="canSendImages" ref="stickerPicker" class="sticker-picker">
                <button
                  type="button"
                  class="quiet-button sticker-toggle"
                  title="表情"
                  aria-label="表情"
                  aria-haspopup="dialog"
                  :aria-expanded="stickerOpen"
                  :disabled="uploadingConversationIds.has(selectedId)"
                  @click="toggleStickers"
                >
                  <AppIcon name="sticker" :size="18" />
                </button>
                <div v-if="stickerOpen" class="sticker-popover" role="dialog" aria-label="表情">
                  <div class="sticker-tabs" role="tablist">
                    <button
                      type="button"
                      role="tab"
                      :aria-selected="stickerTab === 'recent'"
                      :class="{ active: stickerTab === 'recent' }"
                      @click="stickerTab = 'recent'"
                    >最近</button>
                    <button
                      v-for="pack in stickerPacks"
                      :key="pack.id"
                      type="button"
                      role="tab"
                      :aria-selected="stickerTab === pack.id"
                      :class="{ active: stickerTab === pack.id }"
                      @click="stickerTab = pack.id"
                    >{{ pack.name }}</button>
                    <button type="button" class="sticker-manage" @click="openPackManager">管理</button>
                  </div>
                  <span v-if="stickersLoading" class="sticker-state"><span class="spinner small" />正在加载</span>
                  <span v-else-if="stickersFailed" class="sticker-state">
                    加载失败 <button type="button" class="sticker-retry" @click="loadStickers">重试</button>
                  </span>
                  <span v-else-if="!visibleStickers.length" class="sticker-state">
                    {{ stickerTab === 'recent' ? '还没有收到过表情' : '这个表情包还没有图片' }}
                  </span>
                  <div v-else class="sticker-grid">
                    <button
                      v-for="sticker in visibleStickers"
                      :key="sticker.id"
                      type="button"
                      class="sticker-item"
                      :aria-label="`发送表情 ${sticker.fileName}`"
                      @click="pickSticker(sticker)"
                    >
                      <img :src="sticker.path" :alt="sticker.fileName" loading="lazy">
                    </button>
                  </div>
                </div>
              </div>
              <div v-if="packManageOpen" class="pack-dialog-backdrop" @pointerdown.self="packManageOpen = false">
                <div class="pack-dialog" role="dialog" aria-modal="true" aria-label="表情包">
                  <header>
                    <strong>表情包</strong>
                    <button type="button" class="quiet-button" aria-label="关闭" @click="packManageOpen = false">
                      <AppIcon name="dismiss" :size="12" />
                    </button>
                  </header>
                  <form class="pack-create" @submit.prevent="createStickerPack">
                    <input v-model="newPackName" maxlength="20" placeholder="新表情包名称" aria-label="新表情包名称">
                    <button type="submit" :disabled="packBusy || !newPackName.trim()">新建</button>
                  </form>
                  <ul v-if="stickerPacks.length" class="pack-list">
                    <li v-for="pack in stickerPacks" :key="pack.id" :class="{ active: pack.id === managedPackId }">
                      <button type="button" class="pack-name" @click="selectManagedPack(pack.id)">
                        {{ pack.name }} <small>{{ pack.images.length }}</small>
                      </button>
                      <button type="button" :disabled="packBusy" :aria-label="`上移 ${pack.name}`" @click="moveStickerPack(pack.id, -1)">上移</button>
                      <button type="button" :disabled="packBusy" :aria-label="`下移 ${pack.name}`" @click="moveStickerPack(pack.id, 1)">下移</button>
                    </li>
                  </ul>
                  <p v-else class="sticker-state">还没有表情包。输入名称新建一个。</p>
                  <section v-if="managedPack" class="pack-detail">
                    <form class="pack-create" @submit.prevent="renameStickerPack">
                      <input v-model="renamedPackName" maxlength="20" aria-label="表情包名称">
                      <button type="submit" :disabled="packBusy || !renamedPackName.trim() || renamedPackName.trim() === managedPack.name">重命名</button>
                      <button type="button" class="danger" :disabled="packBusy" @click="deleteStickerPack">删除</button>
                    </form>
                    <div v-if="managedPack.images.length" class="sticker-grid">
                      <div v-for="image in managedPack.images" :key="image.id" class="pack-image">
                        <img :src="image.path" :alt="image.fileName" loading="lazy">
                        <button type="button" :disabled="packBusy" :aria-label="`移除 ${image.fileName}`" @click="removePackImage(image)">
                          <AppIcon name="dismiss" :size="12" />
                        </button>
                      </div>
                    </div>
                    <p v-else class="sticker-state">这个表情包还没有图片。</p>
                    <label class="pack-add">
                      添加图片
                      <input type="file" multiple accept="image/png,image/jpeg,image/gif,image/webp" :disabled="packBusy" @change="addPackImages">
                    </label>
                    <template v-if="stickers?.length">
                      <h4>从最近添加</h4>
                      <div class="sticker-grid">
                        <button
                          v-for="sticker in stickers"
                          :key="sticker.id"
                          type="button"
                          class="sticker-item"
                          :disabled="packBusy"
                          :aria-label="`添加 ${sticker.fileName}`"
                          @click="collectSticker(sticker)"
                        >
                          <img :src="sticker.path" :alt="sticker.fileName" loading="lazy">
                        </button>
                      </div>
                    </template>
                  </section>
                </div>
              </div>
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

    <section v-if="showFiltered" class="instances-pane" aria-label="已过滤">
      <header class="instances-header">
        <button class="quiet-button" type="button" aria-label="返回收件箱" title="返回收件箱" @click="showFiltered = false">
          <AppIcon name="back" :size="18" />
        </button>
        <div>
          <h1>已过滤</h1>
          <p>{{ snapshot.filteredCount }} 条消息被规则拦下，不进入收件箱和 AI 队列</p>
        </div>
      </header>
      <ul class="filtered-list">
        <li v-for="message in filteredMessages" :key="message.id" class="filtered-item">
          <div class="filtered-head">
            <strong>{{ message.senderName }}</strong>
            <span class="channel-tag channel-tone" :class="`tone-${channelTone(normalizeChannelLabel(message.channelLabel))}`">{{ normalizeChannelLabel(message.channelLabel) }}</span>
            <span class="filtered-rule">{{ filterRuleLabel(message) }}</span>
            <time :datetime="isoTime(message.occurredAt)" :title="formatFullStamp(message.occurredAt)">{{ relativeAge(message.occurredAt) }}</time>
          </div>
          <p class="filtered-body">{{ message.body }}</p>
          <div class="filtered-actions">
            <FluentButton type="button" tone="subtle" @click="restoreFiltered(message, false)">恢复</FluentButton>
            <FluentButton type="button" tone="subtle" @click="restoreFiltered(message, true)">恢复并加入白名单</FluentButton>
          </div>
        </li>
      </ul>
      <div v-if="!filteredMessages.length && !filteredLoading" class="empty-state">
        <span class="empty-glyph"><AppIcon name="filter" :size="22" /></span>
        <p>没有被过滤的消息</p>
      </div>
      <div v-if="filteredLoading && !filteredMessages.length" class="loading-state"><span class="spinner" />正在载入</div>
    </section>

    <section v-if="showInstances" class="instances-pane" aria-label="接入管理">
      <header class="instances-header">
        <button class="quiet-button" type="button" aria-label="返回收件箱" title="返回收件箱" @click="showInstances = false">
          <AppIcon name="back" :size="18" />
        </button>
        <div>
          <h1>接入管理</h1>
          <p>{{ snapshot.connectors.length }} 个账号 · {{ onlineConnectorCount }} 个在线<span v-if="degradedConnectorCount"> · {{ degradedConnectorCount }} 个部分同步</span></p>
        </div>
      </header>
      <section class="push-panel" aria-label="手机通知">
        <h2>手机通知</h2>
        <p v-if="iosNeedsInstall">iPhone 需要先在 Safari 中点“分享”，选择“添加到主屏幕”，再从主屏幕图标打开本应用后开启通知。</p>
        <p v-else-if="!pushSupported">当前浏览器不支持推送通知。</p>
        <template v-else>
          <p>
            {{ pushEnabled ? '本设备已开启，私聊和被提及的群聊消息会推送到这里。' : '本设备未开启。' }}
            <span v-if="pushDevices.length">已登记 {{ pushDevices.length }} 台设备：{{ pushDevices.map((device) => device.label).join('、') }}。</span>
          </p>
          <div class="push-actions">
            <FluentButton v-if="!pushEnabled" class="accent-button" tone="primary" type="button" :disabled="pushBusy" @click="enablePush">开启通知</FluentButton>
            <FluentButton v-else type="button" :disabled="pushBusy" @click="disablePush">关闭通知</FluentButton>
            <FluentButton type="button" :disabled="pushBusy || !pushDevices.length" @click="sendTestPush">发送测试通知</FluentButton>
          </div>
        </template>
      </section>
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
            <span class="instance-glyph channel-tone" :class="`tone-${channelTone(channelLabel(connector))}`" aria-hidden="true">
              <AppIcon v-if="channelIcon(channelLabel(connector))" :name="channelIcon(channelLabel(connector))!" :size="18" />
              <template v-else>{{ channelGlyph(channelLabel(connector)) }}</template>
            </span>
            <div class="instance-heading">
              <p>{{ channelLabel(connector) }}</p>
              <h2>{{ connector.accountLabel }}</h2>
            </div>
            <span class="status-pill" :class="connector.state">
              <span class="presence-dot" :class="connector.state" />{{ statusLabel(connector.state) }}
            </span>
          </header>
          <p v-if="connector.lastSeenAt" class="instance-seen">
            <AppIcon :name="statusIcon(connector.state)" :size="14" />
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
          <div class="instance-settings">
            <label class="setting-row">
              <span>AI 权限</span>
              <select :value="connector.agentAccess" @change="setAgentAccess(connector, $event)">
                <option value="none">不可见</option>
                <option value="read">只读</option>
                <option value="send">可发送</option>
              </select>
            </label>
            <details v-if="filterDrafts[connector.id]" class="filter-settings">
              <summary>消息过滤<span v-if="connector.filter.enabled" class="filter-on">已开启</span></summary>
              <label class="check-row"><input v-model="filterDrafts[connector.id].enabled" type="checkbox" @change="filterDrafts[connector.id].dirty = true">启用过滤</label>
              <label class="check-row"><input v-model="filterDrafts[connector.id].linkDrop" type="checkbox" @change="filterDrafts[connector.id].dirty = true">陌生人只发链接的私信</label>
              <label class="check-row"><input v-model="filterDrafts[connector.id].spamKeywords" type="checkbox" @change="filterDrafts[connector.id].dirty = true">垃圾关键词</label>
              <p class="setting-label">自定义规则</p>
              <div v-for="(rule, index) in filterDrafts[connector.id].customRules" :key="index" class="rule-row">
                <select v-model="rule.type" aria-label="规则类型" @change="filterDrafts[connector.id].dirty = true">
                  <option value="sender">发件人含</option>
                  <option value="body">正文含</option>
                  <option value="regex">正则</option>
                </select>
                <input v-model="rule.pattern" type="text" maxlength="200" aria-label="规则内容" @input="filterDrafts[connector.id].dirty = true">
                <button type="button" class="quiet-button" aria-label="删除规则" title="删除规则" @click="removeFilterRule(filterDrafts[connector.id], index)"><AppIcon name="dismiss" :size="12" /></button>
              </div>
              <button type="button" class="link-button" @click="addFilterRule(filterDrafts[connector.id])">添加规则</button>
              <p class="setting-label">白名单（每行一个发件人或会话 ID）</p>
              <textarea v-model="filterDrafts[connector.id].allowlistText" rows="3" aria-label="白名单" @input="filterDrafts[connector.id].dirty = true" />
              <FluentButton type="button" :disabled="!filterDrafts[connector.id].dirty" @click="saveFilter(connector)">保存</FluentButton>
            </details>
          </div>
          <footer class="instance-actions">
            <FluentButton
              class="instance-open-button"
              tone="subtle"
              type="button"
              :disabled="!snapshot.conversations.some((conversation) => conversation.connectorId === connector.id)"
              @click="selectFilter(`channel:${channelLabel(connector)}`, connector.id)"
            ><span>查看此账号会话</span><AppIcon name="arrowRight" :size="14" /></FluentButton>
            <FluentButton
              v-if="connector.native"
              class="instance-open-button"
              tone="subtle"
              type="button"
              @click="showNativeView(connector)"
            ><span>原生模式</span><AppIcon name="arrowRight" :size="14" /></FluentButton>
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
