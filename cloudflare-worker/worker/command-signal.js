// The socket only says "command"; the device leases commands over HTTP, so a missed signal waits for its next poll.
export class CommandSignal {
  constructor(state) {
    this.state = state;
    // Keep-alive pings are answered without waking the object.
    state.setWebSocketAutoResponse(new WebSocketRequestResponsePair("ping", "pong"));
  }

  async fetch(request) {
    const connectorId = request.headers.get("x-connector-id") || "";
    if (request.method === "POST") {
      for (const socket of this.state.getWebSockets(connectorId)) {
        try {
          socket.send("command");
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
    this.state.acceptWebSocket(server, [connectorId]);
    return new Response(null, { status: 101, webSocket: client });
  }

  webSocketMessage() {}

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
