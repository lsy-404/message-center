// The server only says "changed" on this socket; the page then reloads through the ordinary inbox request.
const PING_MS = 60_000
const DEAD_MS = 150_000

export function createLiveSignal(onChanged, url = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/live`) {
  let socket
  let pingTimer
  let retryTimer
  let lastHeard = 0
  let backoff = 1_000
  let running = false

  const cleanup = () => {
    if (pingTimer !== undefined) window.clearInterval(pingTimer)
    pingTimer = undefined
    if (socket) {
      socket.onopen = socket.onmessage = socket.onclose = socket.onerror = null
      try { socket.close() } catch { /* already closed */ }
    }
    socket = undefined
  }

  const retry = () => {
    cleanup()
    if (!running) return
    retryTimer = window.setTimeout(connect, backoff)
    backoff = Math.min(backoff * 2, 60_000)
  }

  const connect = () => {
    retryTimer = undefined
    if (!running) return
    socket = new WebSocket(url)
    socket.onopen = () => {
      backoff = 1_000
      lastHeard = Date.now()
      onChanged()
      pingTimer = window.setInterval(() => {
        if (Date.now() - lastHeard > DEAD_MS) return retry()
        socket?.send('ping')
      }, PING_MS)
    }
    socket.onmessage = (event) => {
      lastHeard = Date.now()
      if (event.data === 'changed') onChanged()
    }
    socket.onclose = retry
    socket.onerror = retry
  }

  return {
    start() {
      if (running) return
      running = true
      connect()
    },
    connected() {
      return socket?.readyState === WebSocket.OPEN
    },
    stop() {
      running = false
      if (retryTimer !== undefined) window.clearTimeout(retryTimer)
      retryTimer = undefined
      cleanup()
    },
  }
}
