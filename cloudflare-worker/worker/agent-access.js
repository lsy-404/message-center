// AI access rules and internal message marks.
//
// Every conversation resolves four switches for the agent:
//   visible  - the agent may read the conversation (pull tools, claimed context)
//   push     - new direct messages, or group @/keyword mentions, enter the
//              agent's immediate queue (ordinary group chatter never does)
//   commands - message content may carry instructions; only senders listed in
//              commandSenders ("*" for everyone) actually hold that authority
//   reply    - the agent may queue a reply to a message it holds
// Values come from the conversation override, then the connector default for
// the conversation's category, then the built-in default below.

export const AGENT_ACCESS_KEYS = Object.freeze(["visible", "push", "commands", "reply"]);
export const AGENT_ACCESS_CATEGORIES = Object.freeze(["direct", "group", "group_assistant"]);

export const BUILT_IN_AGENT_ACCESS = Object.freeze({
  direct: Object.freeze({ visible: true, push: true, commands: false, reply: true }),
  group: Object.freeze({ visible: true, push: true, commands: false, reply: true }),
  group_assistant: Object.freeze({ visible: true, push: false, commands: false, reply: false }),
});

// Internal bit flags stored nowhere outside Message Center; they are derived
// per read and never sent to the external channel.
export const MESSAGE_MARKS = Object.freeze({
  sentByAgent: 1,
  sentByOwner: 2,
  readByOwner: 4,
  readByAgent: 8,
  noCommandAuthority: 16,
});

const MARK_NAMES = Object.freeze([
  [MESSAGE_MARKS.sentByAgent, "sent_by_agent"],
  [MESSAGE_MARKS.sentByOwner, "sent_by_owner"],
  [MESSAGE_MARKS.readByOwner, "read_by_owner"],
  [MESSAGE_MARKS.readByAgent, "read_by_agent"],
  [MESSAGE_MARKS.noCommandAuthority, "no_command_authority"],
]);

const MAX_COMMAND_SENDERS = 200;

function objectValue(value) {
  if (typeof value === "string") {
    try { return objectValue(JSON.parse(value)); } catch { return {}; }
  }
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function flags(value) {
  const input = objectValue(value);
  const result = {};
  for (const key of AGENT_ACCESS_KEYS) {
    if (typeof input[key] === "boolean") result[key] = input[key];
  }
  return result;
}

export function accessCategory(conversationType, placement) {
  if (conversationType !== "group") return "direct";
  return placement === "folded" || placement === "message_box" ? "group_assistant" : "group";
}

export function normalizeConnectorAgentSettings(value) {
  const input = objectValue(value);
  const result = {};
  for (const category of AGENT_ACCESS_CATEGORIES) {
    const categoryFlags = flags(input[category]);
    if (Object.keys(categoryFlags).length) result[category] = categoryFlags;
  }
  return result;
}

export function normalizeCommandSenders(value) {
  if (!Array.isArray(value)) return undefined;
  const senders = [];
  for (const item of value) {
    const sender = String(item ?? "").trim();
    if (!sender || sender.length > 300 || senders.includes(sender)) continue;
    senders.push(sender);
    if (senders.length >= MAX_COMMAND_SENDERS) break;
  }
  return senders;
}

export function normalizeConversationAgentSettings(value) {
  const input = objectValue(value);
  const result = flags(input);
  const commandSenders = normalizeCommandSenders(input.commandSenders);
  if (commandSenders) result.commandSenders = commandSenders;
  return result;
}

// Conversations enrolled through the older trust policy keep their meaning:
// they accept commands from the listed senders (everyone when the list is
// empty), behind the configured prefix, and reply unless the policy said none.
export function legacyEnrollment(trustTier, policy) {
  if (trustTier !== "trusted" || !policy || policy.enabled !== true) return null;
  const allowed = Array.isArray(policy.allowedSenderIds) ? policy.allowedSenderIds.map(String) : [];
  return {
    commands: true,
    reply: policy.replyPolicy !== "none",
    commandSenders: allowed.length ? allowed : ["*"],
    commandPrefix: typeof policy.requiredPrefix === "string" ? policy.requiredPrefix : "",
  };
}

export function resolveAgentAccess({
  conversationType, placement, connectorSettings, conversationSettings, legacy = null,
}) {
  const category = accessCategory(conversationType, placement);
  const connector = normalizeConnectorAgentSettings(connectorSettings)[category] || {};
  const conversation = normalizeConversationAgentSettings(conversationSettings);
  const legacyFlags = legacy ? { commands: legacy.commands, reply: legacy.reply } : {};
  const configured = {};
  const sources = {};
  for (const key of AGENT_ACCESS_KEYS) {
    if (key in conversation) {
      configured[key] = conversation[key];
      sources[key] = "conversation";
    } else if (key in legacyFlags) {
      configured[key] = legacyFlags[key];
      sources[key] = "conversation";
    } else if (key in connector) {
      configured[key] = connector[key];
      sources[key] = "connector";
    } else {
      configured[key] = BUILT_IN_AGENT_ACCESS[category][key];
      sources[key] = "default";
    }
  }
  // An invisible conversation is closed to the agent entirely.
  const visible = configured.visible;
  return {
    category,
    visible,
    push: visible && configured.push,
    commands: visible && configured.commands,
    reply: visible && configured.reply,
    configured,
    sources,
    commandSenders: conversation.commandSenders ?? legacy?.commandSenders ?? [],
    commandPrefix: legacy?.commandPrefix || "",
  };
}

export function commandAuthority(access, senderId, body) {
  if (!access.visible) return { authorized: false, reason: "not_visible" };
  if (!access.commands) return { authorized: false, reason: "commands_disabled" };
  const sender = String(senderId ?? "").trim();
  if (!access.commandSenders.includes("*") && !(sender && access.commandSenders.includes(sender))) {
    return { authorized: false, reason: "sender_not_authorized" };
  }
  if (access.commandPrefix && !String(body ?? "").trimStart().startsWith(access.commandPrefix)) {
    return { authorized: false, reason: "command_prefix_missing" };
  }
  return { authorized: true, reason: "authorized_sender" };
}

export function authorRole(direction, createdBy) {
  if (direction !== "outbound") return "contact";
  return String(createdBy ?? "").startsWith("agent:") ? "agent" : "owner";
}

export function messageMarks({ role, ownerReadAt, agentReadAt, agentQueueState, commandAuthorized }) {
  let marks = 0;
  if (role === "agent") marks |= MESSAGE_MARKS.sentByAgent | MESSAGE_MARKS.readByAgent;
  if (role === "owner") marks |= MESSAGE_MARKS.sentByOwner | MESSAGE_MARKS.readByOwner;
  if (ownerReadAt) marks |= MESSAGE_MARKS.readByOwner;
  if (agentReadAt || (agentQueueState && agentQueueState !== "pending")) marks |= MESSAGE_MARKS.readByAgent;
  if (role === "contact" && !commandAuthorized) marks |= MESSAGE_MARKS.noCommandAuthority;
  return marks;
}

export function markNames(marks) {
  return MARK_NAMES.filter(([bit]) => (marks & bit) === bit).map(([, name]) => name);
}
