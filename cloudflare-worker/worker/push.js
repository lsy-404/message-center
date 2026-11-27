import { buildPushHTTPRequest } from "@pushforge/builder";

const COALESCE_SECONDS = 60;
const PREVIEW_CHARS = 100;
const PUSH_TTL_SECONDS = 3600;

function parseJson(value) {
  try { return JSON.parse(value); } catch { return {}; }
}

export function pushConfigured(env) {
  return Boolean(env.VAPID_PUBLIC_KEY && env.VAPID_PRIVATE_KEY);
}

export function deviceLabel(userAgent) {
  const ua = String(userAgent || "");
  const system = /iPhone/.test(ua) ? "iPhone" : /iPad/.test(ua) ? "iPad" : /Android/.test(ua) ? "Android"
    : /Windows/.test(ua) ? "Windows" : /Macintosh/.test(ua) ? "Mac" : /Linux/.test(ua) ? "Linux" : "设备";
  const browser = /Edg\//.test(ua) ? "Edge" : /Firefox\//.test(ua) ? "Firefox"
    : /Chrome\/|CriOS\//.test(ua) ? "Chrome" : /Safari\//.test(ua) ? "Safari" : "";
  return `${system}${browser ? ` · ${browser}` : ""}`;
}

// Resolves to "sent", "gone" (subscription removed) or "failed".
async function sendOne(env, privateJWK, adminContact, subscription, payload) {
  try {
    const { endpoint, headers, body } = await buildPushHTTPRequest({
      privateJWK,
      subscription: { endpoint: subscription.endpoint, keys: { p256dh: subscription.p256dh, auth: subscription.auth } },
      message: { payload, adminContact, options: { ttl: PUSH_TTL_SECONDS, urgency: "high" } },
    });
    const response = await fetch(endpoint, { method: "POST", headers, body });
    if (response.status === 404 || response.status === 410) {
      await env.DB.prepare("DELETE FROM push_subscriptions WHERE endpoint = ?").bind(subscription.endpoint).run();
      return "gone";
    }
    if (!response.ok) {
      console.error(JSON.stringify({ event: "push_rejected", status: response.status,
        host: new URL(subscription.endpoint).host }));
      return "failed";
    }
    await env.DB.prepare("UPDATE push_subscriptions SET last_success_at = ? WHERE endpoint = ?")
      .bind(new Date().toISOString(), subscription.endpoint).run();
    return "sent";
  } catch (error) {
    console.error(JSON.stringify({ event: "push_failed", message: error instanceof Error ? error.message : String(error) }));
    return "failed";
  }
}

export async function deliverPush(env, payload, ownerId) {
  const result = { sent: 0, gone: 0, failed: 0 };
  if (!pushConfigured(env)) return result;
  const rows = (ownerId
    ? await env.DB.prepare("SELECT endpoint, p256dh, auth FROM push_subscriptions WHERE owner_id = ?").bind(ownerId).all()
    : await env.DB.prepare("SELECT endpoint, p256dh, auth FROM push_subscriptions").all()).results || [];
  if (!rows.length) return result;
  const privateJWK = JSON.parse(env.VAPID_PRIVATE_KEY);
  const adminContact = env.VAPID_SUBJECT || new URL(env.OIDC_REDIRECT_URI).origin;
  const outcomes = await Promise.all(rows.map((row) => sendOne(env, privateJWK, adminContact, row, payload)));
  for (const outcome of outcomes) result[outcome] += 1;
  return result;
}

function previewText(body) {
  const flat = String(body || "").replace(/\s+/g, " ").trim() || "[附件]";
  const chars = Array.from(flat);
  return chars.length > PREVIEW_CHARS ? `${chars.slice(0, PREVIEW_CHARS).join("")}…` : flat;
}

// Notifies for messages that were just stored; filtered, muted, background and
// own messages never notify, and each conversation pushes at most once per minute.
export async function notifyInbound(env, messageIds) {
  if (!pushConfigured(env)) return;
  const any = await env.DB.prepare("SELECT 1 AS found FROM push_subscriptions LIMIT 1").first();
  if (!any) return;
  for (const messageId of messageIds) {
    const row = await env.DB.prepare(`
      SELECT m.sender_name, m.body, m.queue_class, m.direction, m.metadata_json, c.id AS conversation_id,
        COALESCE(ct.display_name, p.display_name, c.title) AS title, COALESCE(p.is_muted, 0) AS muted
      FROM messages m JOIN conversations c ON c.id = m.conversation_id
      LEFT JOIN conversation_profiles p ON p.connector_id = c.connector_id AND p.conversation_external_id = c.external_id
      LEFT JOIN contact_conversations cc ON cc.conversation_id = c.id
      LEFT JOIN contacts ct ON ct.id = cc.contact_id
      WHERE m.id = ?
    `).bind(messageId).first();
    if (!row || row.direction !== "inbound" || row.queue_class !== "immediate" || row.muted) continue;
    const metadata = parseJson(row.metadata_json);
    if (metadata.presentation === "system") continue;
    const direct = metadata.conversationType !== "group";
    if (!(direct ? (metadata.trigger || "direct") === "direct" : metadata.trigger === "mention")) continue;

    const stamp = new Date().toISOString();
    const cutoff = new Date(Date.now() - COALESCE_SECONDS * 1000).toISOString();
    const claimed = await env.DB.prepare(`
      INSERT INTO push_conversation_state (conversation_id, last_notified_at) VALUES (?, ?)
      ON CONFLICT(conversation_id) DO UPDATE SET last_notified_at = excluded.last_notified_at
      WHERE push_conversation_state.last_notified_at <= ?
    `).bind(row.conversation_id, stamp, cutoff).run();
    if (!claimed.meta?.changes) continue;

    const sender = String(row.sender_name || "");
    const preview = previewText(row.body);
    await deliverPush(env, {
      title: String(row.title || "Message Center").slice(0, 100),
      body: sender && sender !== row.title ? `${sender}: ${preview}` : preview,
      tag: row.conversation_id,
      conversationId: row.conversation_id,
    });
  }
}
