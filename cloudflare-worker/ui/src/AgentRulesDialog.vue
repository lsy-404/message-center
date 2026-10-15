<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { FluentButton, FluentCheckbox, FluentDialog } from '@platform-kit/fluent/vue'
import AppIcon from './AppIcon.vue'
import { api } from './http'
import {
  AGENT_ACCESS_KEYS,
  agentCategoryLabel,
  agentKeyCopy,
  agentSourceLabel,
  type AgentAccess,
  type AgentAccessKey,
  type AgentCategory,
  type AgentFlags,
  type AgentSource,
} from './agent-rules.mjs'

type Choice = 'inherit' | 'on' | 'off'
type ConversationSettings = Partial<AgentFlags> & { commandSenders?: string[] }
type Sender = { id: string, name: string, lastSeenAt: string, messageCount: number, commandAuthority: boolean }
type SettingsResponse = {
  category: AgentCategory
  settings: ConversationSettings
  inherited: AgentFlags
  configured: AgentFlags
  effective: AgentAccess
  sources: Record<AgentAccessKey, AgentSource>
  commandSenders: string[]
  commandPrefix: string
  senders: Sender[]
}

const props = defineProps<{ open: boolean, conversationId: string, conversationTitle: string }>()
const emit = defineEmits<{ 'update:open': [value: boolean], saved: [] }>()

const data = ref<SettingsResponse | null>(null)
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const choices = ref<Record<AgentAccessKey, Choice>>({ visible: 'inherit', push: 'inherit', commands: 'inherit', reply: 'inherit' })
const selectedSenders = ref<string[]>([])
const allSenders = ref(false)
let loadToken = 0

const choiceOptions: { value: Choice, label: string }[] = [
  { value: 'inherit', label: '继承' },
  { value: 'on', label: '开' },
  { value: 'off', label: '关' },
]

const preview = computed(() => {
  const current = data.value
  if (!current) return null
  const value = (key: AgentAccessKey) => choices.value[key] === 'inherit'
    ? (current.settings[key] === undefined ? current.configured[key] : current.inherited[key])
    : choices.value[key] === 'on'
  const visible = value('visible')
  return {
    visible,
    push: visible && value('push'),
    commands: visible && value('commands'),
    reply: visible && value('reply'),
  } as AgentFlags
})

const senderRows = computed(() => {
  const known = new Map((data.value?.senders ?? []).map((sender) => [sender.id, sender]))
  for (const id of selectedSenders.value) {
    if (!known.has(id)) known.set(id, { id, name: id, lastSeenAt: '', messageCount: 0, commandAuthority: true })
  }
  return [...known.values()]
})

function inheritedText(key: AgentAccessKey) {
  const current = data.value
  if (!current) return ''
  if (current.settings[key] !== undefined) return current.inherited[key] ? '开' : '关'
  return `${current.configured[key] ? '开' : '关'} · ${agentSourceLabel(current.sources[key])}`
}

async function load() {
  const token = ++loadToken
  loading.value = true
  error.value = ''
  try {
    const result = await api<SettingsResponse>(`/api/conversations/${encodeURIComponent(props.conversationId)}/agent-settings`)
    if (token !== loadToken) return
    data.value = result
    for (const key of AGENT_ACCESS_KEYS) {
      const value = result.settings[key]
      choices.value[key] = value === undefined ? 'inherit' : value ? 'on' : 'off'
    }
    const senders = result.settings.commandSenders ?? result.commandSenders
    allSenders.value = senders.includes('*')
    selectedSenders.value = senders.filter((sender) => sender !== '*')
  } catch (caught) {
    if (token === loadToken) error.value = caught instanceof Error ? caught.message : String(caught)
  } finally {
    if (token === loadToken) loading.value = false
  }
}

watch(() => [props.open, props.conversationId] as const, ([open]) => {
  if (open) void load()
}, { immediate: true })

function toggleSender(id: string, checked: boolean) {
  selectedSenders.value = checked
    ? [...new Set([...selectedSenders.value, id])]
    : selectedSenders.value.filter((sender) => sender !== id)
}

function resetToDefaults() {
  for (const key of AGENT_ACCESS_KEYS) choices.value[key] = 'inherit'
  selectedSenders.value = []
  allSenders.value = false
}

function close() {
  emit('update:open', false)
}

async function save() {
  const current = data.value
  if (!current || saving.value) return
  const settings: ConversationSettings = {}
  for (const key of AGENT_ACCESS_KEYS) {
    if (choices.value[key] !== 'inherit') settings[key] = choices.value[key] === 'on'
  }
  const senders = allSenders.value ? ['*'] : selectedSenders.value
  if (senders.length || current.settings.commandSenders !== undefined) settings.commandSenders = senders
  saving.value = true
  error.value = ''
  try {
    data.value = await api<SettingsResponse>(`/api/conversations/${encodeURIComponent(props.conversationId)}/agent-settings`, {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ settings }),
    })
    emit('saved')
    close()
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : String(caught)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <FluentDialog class="agent-rules-dialog" :open="open" label="AI 规则" close-on-outside @update:open="emit('update:open', $event)">
    <template #title>
      <span class="agent-rules-title">
        <AppIcon name="bot" :size="20" />AI 规则
      </span>
      <span class="agent-rules-subtitle">{{ conversationTitle }}<template v-if="data"> · {{ agentCategoryLabel(data.category) }}</template></span>
    </template>

    <div v-if="loading && !data" class="loading-state"><span class="spinner" />正在载入</div>
    <template v-else-if="data">
      <ul class="agent-rule-list">
        <li v-for="key in AGENT_ACCESS_KEYS" :key="key" class="agent-rule" :data-rule="key">
          <span class="agent-rule-copy">
            <strong>{{ agentKeyCopy(key, data.category).label }}</strong>
            <small>{{ agentKeyCopy(key, data.category).description }}</small>
          </span>
          <span class="segmented agent-rule-choice" role="radiogroup" :aria-label="agentKeyCopy(key, data.category).label">
            <button
              v-for="option in choiceOptions"
              :key="option.value"
              type="button"
              role="radio"
              :class="{ active: choices[key] === option.value }"
              :aria-checked="choices[key] === option.value"
              :title="option.value === 'inherit' ? `继承：${inheritedText(key)}` : undefined"
              @click="choices[key] = option.value"
            >{{ option.value === 'inherit' ? `继承（${inheritedText(key).slice(0, 1)}）` : option.label }}</button>
          </span>
          <span v-if="preview && key !== 'visible' && !preview.visible" class="agent-rule-note">AI 不可见时不生效</span>
        </li>
      </ul>

      <section class="agent-senders" :class="{ disabled: !preview?.commands }" aria-label="指令权限">
        <header>
          <strong>可以下指令的发送人</strong>
          <small v-if="preview?.commands">未勾选的发送人消息会标注“无指令权限”</small>
          <small v-else>开启“接受指令”后生效</small>
        </header>
        <FluentCheckbox :model-value="allSenders" :disabled="!preview?.commands" @update:model-value="allSenders = $event">
          所有发送人
        </FluentCheckbox>
        <ul v-if="senderRows.length" class="agent-sender-list">
          <li v-for="sender in senderRows" :key="sender.id">
            <FluentCheckbox
              :model-value="allSenders || selectedSenders.includes(sender.id)"
              :disabled="!preview?.commands || allSenders"
              @update:model-value="toggleSender(sender.id, $event)"
            >
              <span class="agent-sender-name">{{ sender.name }}</span>
              <span v-if="sender.messageCount" class="agent-sender-meta">{{ sender.messageCount }} 条消息</span>
            </FluentCheckbox>
          </li>
        </ul>
        <p v-else class="agent-senders-empty">这个会话里还没有可识别的发送人</p>
        <p v-if="data.commandPrefix" class="agent-senders-empty">旧版策略要求指令以 {{ data.commandPrefix }} 开头</p>
      </section>
    </template>
    <p v-if="error" class="agent-rules-error" role="alert">{{ error }}</p>

    <template #footer>
      <FluentButton type="button" tone="subtle" :disabled="!data || saving" @click="resetToDefaults">全部继承</FluentButton>
      <span class="agent-rules-spacer" />
      <FluentButton type="button" :disabled="saving" @click="close">取消</FluentButton>
      <FluentButton type="button" tone="primary" :disabled="!data || saving" @click="save">保存</FluentButton>
    </template>
  </FluentDialog>
</template>
