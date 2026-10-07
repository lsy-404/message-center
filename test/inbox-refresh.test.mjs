import assert from 'node:assert/strict'
import { createInboxReadGate, createInboxRefreshLoop } from '../cloudflare-worker/ui/src/inbox-refresh.mjs'

class FakeTimers {
  time = 0
  nextId = 1
  jobs = new Map()

  setTimeout(callback, delay) {
    const id = this.nextId++
    this.jobs.set(id, { callback, at: this.time + delay })
    return id
  }

  clearTimeout(id) {
    this.jobs.delete(id)
  }

  async advance(duration) {
    const end = this.time + duration
    while (true) {
      const next = [...this.jobs.entries()].sort((a, b) => a[1].at - b[1].at)[0]
      if (!next || next[1].at > end) break
      this.jobs.delete(next[0])
      this.time = next[1].at
      next[1].callback()
      await Promise.resolve()
      await Promise.resolve()
    }
    this.time = end
    await Promise.resolve()
  }
}

function deferred() {
  let resolve
  const promise = new Promise((done) => { resolve = done })
  return { promise, resolve }
}

const slowTimers = new FakeTimers()
let requestCount = 0
let pending
const slowLoop = createInboxRefreshLoop(() => {
  requestCount += 1
  if (requestCount === 1) {
    pending = deferred()
    return pending.promise
  }
  return Promise.resolve()
}, () => true, slowTimers)
slowLoop.start(true)
await slowTimers.advance(0)
assert.equal(requestCount, 1)
await slowTimers.advance(60_000)
assert.equal(requestCount, 1, 'a slow inbox read must not overlap or starve the refresh loop')
pending.resolve()
await Promise.resolve()
await Promise.resolve()
await slowTimers.advance(5_000)
assert.equal(requestCount, 2, 'the next refresh starts only after the previous read settles')
slowLoop.stop()

const retryTimers = new FakeTimers()
let attempts = 0
const retryLoop = createInboxRefreshLoop(() => {
  attempts += 1
  return Promise.reject(new Error('offline'))
}, () => true, retryTimers)
retryLoop.start(true)
await retryTimers.advance(0)
assert.equal(attempts, 1)
await retryTimers.advance(9_999)
assert.equal(attempts, 1)
await retryTimers.advance(1)
assert.equal(attempts, 2, 'first failure backs off to ten seconds')
await retryTimers.advance(19_999)
assert.equal(attempts, 2)
await retryTimers.advance(1)
assert.equal(attempts, 3, 'each failure doubles the delay')
await retryTimers.advance(39_999)
assert.equal(attempts, 3)
await retryTimers.advance(1)
assert.equal(attempts, 4)
await retryTimers.advance(60_000)
assert.equal(attempts, 5, 'failure backoff is capped at one minute')
retryLoop.stop()

const visibilityTimers = new FakeTimers()
let visible = true
let visibleAttempts = 0
const visibilityLoop = createInboxRefreshLoop(async () => { visibleAttempts += 1 }, () => visible, visibilityTimers)
visibilityLoop.start(true)
await visibilityTimers.advance(0)
assert.equal(visibleAttempts, 1)
visible = false
visibilityLoop.stop()
await visibilityTimers.advance(60_000)
assert.equal(visibleAttempts, 1, 'hidden or offline state leaves no timer running')
visible = true
visibilityLoop.start(true)
await visibilityTimers.advance(0)
assert.equal(visibleAttempts, 2, 'recovery triggers an immediate refresh')
visibilityLoop.stop()

const reads = createInboxReadGate()
const firstRead = reads.begin('first')
assert.equal(reads.isBusy(), true)
const secondRead = reads.begin('second')
assert.equal(firstRead.controller.signal.aborted, true, 'changing sessions aborts the prior GET')
reads.finish(firstRead)
assert.equal(reads.isBusy(), true, 'finishing a superseded request cannot clear the current request')
assert.equal(reads.isCurrent(firstRead, 'second'), false, 'a stale session response cannot apply')
assert.equal(reads.isCurrent(secondRead, 'second'), true)
assert.equal(reads.isActive(secondRead), true)
reads.cancel()
assert.equal(secondRead.controller.signal.aborted, true)
assert.equal(reads.isBusy(), false)

console.log('Inbox refresh tests passed')
