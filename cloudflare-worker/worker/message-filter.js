// Built-in spam list. Kept short and literal so a filtered message can always be explained by one entry.
export const SPAM_KEYWORDS = {
  // Matched anywhere in the body (case-insensitive).
  any: [
    "回t退订", "回td退订", "退订回t", "退订回td", "拒收请回", "reply stop to unsubscribe",
    "无抵押", "低息贷款", "贷款额度", "快速放款", "免息", "提额",
    "恭喜您中奖", "恭喜您获得", "中奖", "代开发票", "刷单", "日结",
    "博彩", "you have won", "claim your prize",
  ],
  // Phishing bait: counts only when the body also contains a link.
  withLink: ["点击领取", "立即领取", "领奖", "积分清零", "账户异常", "已冻结", "解冻", "click here to claim"],
};

const URL_PATTERN = /(?:https?:\/\/|www\.)\S+|\bt\.me\/\S+/gi;
const LINK_ONLY_EXTRA_CHARS = 6;
export const MAX_CUSTOM_RULES = 50;
export const MAX_RULE_PATTERN_LENGTH = 200;
export const MAX_ALLOWLIST_ENTRIES = 200;
const MAX_ENTRY_LENGTH = 200;
const MAX_EVALUATED_BODY = 4000;
const CUSTOM_RULE_TYPES = new Set(["sender", "body", "regex"]);

export const DEFAULT_FILTER_SETTINGS = {
  enabled: false, linkDrop: false, spamKeywords: false, customRules: [], allowlist: [],
};

// Rejects the common catastrophic-backtracking shape: a quantified group that itself contains a quantifier.
function backtrackingRisk(pattern) {
  return /\((?:[^()\\]|\\.)*[+*](?:[^()\\]|\\.)*\)[+*{]/.test(pattern);
}

function compileRegex(pattern) {
  if (backtrackingRisk(pattern)) throw new Error("invalid_filter_rule");
  try { return new RegExp(pattern, "iu"); } catch { throw new Error("invalid_filter_rule"); }
}

export function normalizeFilterSettings(value) {
  const input = value && typeof value === "object" && !Array.isArray(value) ? value : {};
  const rawRules = input.customRules === undefined ? [] : input.customRules;
  const rawAllowlist = input.allowlist === undefined ? [] : input.allowlist;
  if (!Array.isArray(rawRules) || rawRules.length > MAX_CUSTOM_RULES) throw new Error("invalid_filter_rule");
  if (!Array.isArray(rawAllowlist) || rawAllowlist.length > MAX_ALLOWLIST_ENTRIES) throw new Error("invalid_filter_allowlist");
  const customRules = rawRules.map((rule) => {
    const type = String(rule?.type || "");
    const pattern = typeof rule?.pattern === "string" ? rule.pattern.trim() : "";
    if (!CUSTOM_RULE_TYPES.has(type) || !pattern || pattern.length > MAX_RULE_PATTERN_LENGTH) {
      throw new Error("invalid_filter_rule");
    }
    if (type === "regex") compileRegex(pattern);
    return { type, pattern };
  });
  const allowlist = [...new Set(rawAllowlist.map((entry) => {
    const item = typeof entry === "string" ? entry.trim() : "";
    if (!item || item.length > MAX_ENTRY_LENGTH) throw new Error("invalid_filter_allowlist");
    return item;
  }))];
  return {
    enabled: input.enabled === true,
    linkDrop: input.linkDrop === true,
    spamKeywords: input.spamKeywords === true,
    customRules,
    allowlist,
  };
}

export function parseFilterSettings(json) {
  try { return normalizeFilterSettings(JSON.parse(json)); } catch { return { ...DEFAULT_FILTER_SETTINGS }; }
}

function isLinkOnly(body) {
  const links = body.match(URL_PATTERN);
  if (!links) return false;
  const rest = body.replace(URL_PATTERN, "").replace(/[\s\p{P}\p{S}]/gu, "");
  return rest.length <= LINK_ONLY_EXTRA_CHARS;
}

// message: { body, senderId, senderName, conversationExternalId, conversationType, hasAttachments }.
// hasOutboundHistory is awaited only when the link rule needs it.
export async function evaluateMessageFilter(settings, message, hasOutboundHistory) {
  if (!settings.enabled) return null;
  const body = String(message.body || "").slice(0, MAX_EVALUATED_BODY);
  const senderId = String(message.senderId || "");
  const senderName = String(message.senderName || "");
  const allowed = new Set(settings.allowlist.map((entry) => entry.toLowerCase()));
  if ([senderId, senderName, String(message.conversationExternalId || "")]
    .some((value) => value && allowed.has(value.toLowerCase()))) return null;
  const lowerBody = body.toLowerCase();
  for (const rule of settings.customRules) {
    if (rule.type === "sender" && `${senderId}\n${senderName}`.toLowerCase().includes(rule.pattern.toLowerCase())) {
      return { rule: "custom_sender", detail: rule.pattern };
    }
    if (rule.type === "body" && lowerBody.includes(rule.pattern.toLowerCase())) {
      return { rule: "custom_body", detail: rule.pattern };
    }
    if (rule.type === "regex" && compileRegex(rule.pattern).test(body)) {
      return { rule: "custom_regex", detail: rule.pattern };
    }
  }
  if (settings.linkDrop && message.conversationType !== "group" && !message.hasAttachments &&
      isLinkOnly(body) && !await hasOutboundHistory()) {
    return { rule: "link_drop" };
  }
  if (settings.spamKeywords) {
    const hit = SPAM_KEYWORDS.any.find((keyword) => lowerBody.includes(keyword));
    if (hit) return { rule: "spam_keywords", detail: hit };
    if (body.match(URL_PATTERN)) {
      const bait = SPAM_KEYWORDS.withLink.find((keyword) => lowerBody.includes(keyword));
      if (bait) return { rule: "spam_keywords", detail: bait };
    }
  }
  return null;
}
