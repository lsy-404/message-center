export function createInboxReadGate() {
  let active
  return {
    begin(conversationId) {
      active?.controller.abort()
      const request = { conversationId, controller: new AbortController() }
      active = request
      return request
    },
    isCurrent(request, selectedConversationId) {
      return active === request && request.conversationId === selectedConversationId
    },
    isActive(request) {
      return active === request
    },
    isBusy() {
      return active !== undefined
    },
    finish(request) {
      if (active === request) active = undefined
    },
    cancel() {
      active?.controller.abort()
      active = undefined
    },
  }
}

export function createInboxRefreshLoop(refresh, isEnabled, timers = window) {
  let timer
  let running = false
  let inFlight = false
  let wakeAfterFlight = false
  let failures = 0

  const clear = () => {
    if (timer !== undefined) timers.clearTimeout(timer)
    timer = undefined
  }

  const schedule = (delay) => {
    clear()
    if (!running || !isEnabled()) return
    timer = timers.setTimeout(() => {
      timer = undefined
      void run()
    }, delay)
  }

  const run = async () => {
    if (!running || !isEnabled()) return
    if (inFlight) {
      wakeAfterFlight = true
      return
    }
    inFlight = true
    try {
      await refresh()
      failures = 0
    } catch (error) {
      if (running && error?.name !== 'AbortError') failures += 1
    } finally {
      inFlight = false
      if (running && isEnabled()) {
        const delay = wakeAfterFlight ? 0 : Math.min(60_000, 5_000 * (2 ** failures))
        wakeAfterFlight = false
        schedule(delay)
      }
    }
  }

  return {
    start(immediate = false) {
      running = true
      if (inFlight) wakeAfterFlight = immediate
      else schedule(immediate ? 0 : 5_000)
    },
    stop() {
      running = false
      wakeAfterFlight = false
      clear()
    },
    wake() {
      if (!running) return
      if (inFlight) {
        wakeAfterFlight = true
        return
      }
      schedule(0)
    },
  }
}
