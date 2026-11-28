import worker from "./index.js";

// Devices hear "command" and the owner's pages hear "changed"; a missed signal waits for the next poll either way.
// Devices may also send small JSON API calls as {"t":"req"} frames, answered with {"t":"res"} frames.
// Devices ping every 60 seconds, under the edge's 100-second idle limit.
const SIGNAL_LIVE_MS = 150_000;
const OWNER_TAG = "owner";
const MAX_FRAME_BYTES = 1024 * 1024;
const TEXT_ENCODER = new TextEncoder();

export class CommandSignal {
  constructor(state, env) {
    this.state = state;
    this.env = env;
    // Keep-alive pings are answered without waking the object.
    state.setWebSocketAutoResponse(new WebSocketRequestResponsePair("ping", "pong"));
  }

  async fetch(request) {
    if (new URL(request.url).pathname === "/live") return Response.json({ connectors: [...this.live()] });
    const owner = new URL(request.url).pathname === "/owner";
    const tag = owner ? OWNER_TAG : request.headers.get("x-connector-id") || "";
    if (request.method === "POST") {
      for (const socket of this.state.getWebSockets(tag)) {
        try {
          socket.send(owner ? "changed" : "command");
        } catch {
          // A socket closing at this moment reconnects and polls on its own.
        }
      }
      return new Response(null, { status: 204 });
    }
    if ((request.headers.get("upgrade") || "").toLowerCase() !== "websocket") {
      return new Response("websocket_required", { status: 426 });
    }
    const [client, server] = Object.values(new WebSocketPair());
    this.state.acceptWebSocket(server, [tag]);
    server.serializeAttachment({ acceptedAt: Date.now(), origin: new URL(request.url).origin });
    return new Response(null, { status: 101, webSocket: client });
  }

  // Connectors whose socket was opened or answered a ping within SIGNAL_LIVE_MS.
  live() {
    const connectors = new Set();
    for (const socket of this.state.getWebSockets()) {
      const pinged = this.state.getWebSocketAutoResponseTimestamp(socket)?.getTime() || 0;
      const attachment = socket.deserializeAttachment();
      const active = Math.max(pinged, attachment?.acceptedAt || 0, attachment?.lastMessageAt || 0);
      if (Date.now() - active <= SIGNAL_LIVE_MS) {
        for (const tag of this.state.getTags(socket)) if (tag !== OWNER_TAG) connectors.add(tag);
      }
    }
    return connectors;
  }

  async webSocketMessage(socket, message) {
    if (typeof message !== "string") return;
    const oversize = TEXT_ENCODER.encode(message).length > MAX_FRAME_BYTES;
    let frame;
    if (oversize) {
      frame = { id: Number(/"id"\s*:\s*(\d+)/.exec(message.slice(0, 256))?.[1]) };
    } else {
      try {
        frame = JSON.parse(message);
      } catch {
        return;
      }
    }
    if (frame?.t !== "req" && !oversize) return;
    const id = frame?.id;
    if (!Number.isSafeInteger(id)) return;
    const attachment = socket.deserializeAttachment() || {};
    socket.serializeAttachment({ ...attachment, lastMessageAt: Date.now() });
    const reply = (status, body) => {
      try {
        socket.send(JSON.stringify({ t: "res", id, status, body }));
      } catch {
        // The socket closed; the client's call times out and its caller retries.
      }
    };
    if (oversize) return reply(413, JSON.stringify({ ok: false, error: "frame_too_large" }));
    const path = typeof frame.path === "string" ? frame.path : "";
    const method = typeof frame.method === "string" ? frame.method.toUpperCase() : "";
    if (!["GET", "POST", "PUT"].includes(method) || !frame.headers || typeof frame.headers !== "object"
      || Array.isArray(frame.headers)) {
      return reply(400, JSON.stringify({ ok: false, error: "bad_request" }));
    }
    const route = path.split("?")[0];
    if (!route.startsWith("/api/connectors/") || route === "/api/connectors/signal"
      || route.startsWith("/api/connectors/files/")) {
      return reply(404, JSON.stringify({ ok: false, error: "not_dispatchable" }));
    }
    try {
      const init = { method, headers: frame.headers };
      if (method !== "GET" && typeof frame.body === "string") {
        init.body = frame.bodyEncoding === "base64"
          ? Uint8Array.from(atob(frame.body), (char) => char.charCodeAt(0))
          : frame.body;
      }
      const response = await worker.fetch(
        new Request(`${attachment.origin || "https://message-center.internal"}${path}`, init),
        this.dispatchEnv(),
        { waitUntil: (promise) => this.state.waitUntil(promise), passThroughOnException() {} },
      );
      reply(response.status, await response.text());
    } catch (error) {
      console.error(JSON.stringify({ event: "signal_dispatch_failed", path: route,
        message: error instanceof Error ? error.message : String(error) }));
      reply(500, JSON.stringify({ ok: false, error: "dispatch_failed" }));
    }
  }

  // A dispatched route signals through this object directly: an object cannot fetch its own stub.
  dispatchEnv() {
    const self = { fetch: (input, init) => this.fetch(new Request(input, init)) };
    return { ...this.env, COMMAND_SIGNAL: { idFromName: () => "self", get: () => self } };
  }

  webSocketClose(socket, code) {
    try {
      socket.close(code === 1005 || code === 1006 ? 1000 : code, "closed");
    } catch {
      // Already closed by the runtime's automatic close reply.
    }
  }

  webSocketError() {}
}

function signalStub(env) {
  return env.COMMAND_SIGNAL.get(env.COMMAND_SIGNAL.idFromName("commands"));
}

export function openCommandSignal(request, env, connectorId) {
  const headers = new Headers(request.headers);
  headers.set("x-connector-id", connectorId);
  return signalStub(env).fetch(new Request(request.url, { method: "GET", headers }));
}

export async function signalCommand(env, connectorId) {
  if (!env.COMMAND_SIGNAL) return;
  try {
    await signalStub(env).fetch("https://command-signal/notify", {
      method: "POST", headers: { "x-connector-id": connectorId },
    });
  } catch (error) {
    console.error(JSON.stringify({ event: "command_signal_failed",
      message: error instanceof Error ? error.message : String(error) }));
  }
}

export async function liveSignals(env) {
  if (!env.COMMAND_SIGNAL) return new Set();
  try {
    const response = await signalStub(env).fetch("https://command-signal/live");
    return new Set((await response.json()).connectors || []);
  } catch (error) {
    console.error(JSON.stringify({ event: "command_signal_live_failed",
      message: error instanceof Error ? error.message : String(error) }));
    return new Set();
  }
}

export function openOwnerSignal(request, env) {
  return signalStub(env).fetch(new Request("https://command-signal/owner", { method: "GET", headers: request.headers }));
}

export async function signalOwner(env) {
  if (!env.COMMAND_SIGNAL) return;
  try {
    await signalStub(env).fetch("https://command-signal/owner", { method: "POST" });
  } catch (error) {
    console.error(JSON.stringify({ event: "owner_signal_failed",
      message: error instanceof Error ? error.message : String(error) }));
  }
}
