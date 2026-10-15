export type AgentAccessKey = 'visible' | 'push' | 'commands' | 'reply'
export type AgentCategory = 'direct' | 'group' | 'group_assistant'
export type AgentFlags = Record<AgentAccessKey, boolean>
export type AgentAccess = AgentFlags & { category: AgentCategory }
export type AgentSource = 'default' | 'connector' | 'conversation'
export type ConnectorAgentSettings = Partial<Record<AgentCategory, Partial<AgentFlags>>>
export type MarkTag = { key: string, label: string, tone: 'ai' | 'owner' | 'muted' | 'unread' | 'warning' }

export const AGENT_ACCESS_KEYS: AgentAccessKey[]
export const AGENT_CATEGORIES: AgentCategory[]
export const MESSAGE_MARK_BITS: {
  sentByAgent: number
  sentByOwner: number
  readByOwner: number
  readByAgent: number
  noCommandAuthority: number
}
export function agentCategoryLabel(category: unknown): string
export function agentCategoryShortLabel(category: unknown): string
export function agentSourceLabel(source: unknown): string
export function agentKeyCopy(key: AgentAccessKey, category?: AgentCategory): { label: string, description: string }
export function agentColumnLabel(key: AgentAccessKey): string
export function agentAccessSummary(access: AgentAccess | null | undefined): string[]
export function setConnectorOverride(
  settings: ConnectorAgentSettings | null | undefined, category: AgentCategory, key: AgentAccessKey, value: boolean,
): ConnectorAgentSettings
export function describeMarks(marks: unknown): string
export function messageMarkTags(
  marks: unknown, options?: { commandsAccepted?: boolean, agentPushes?: boolean },
): MarkTag[]
