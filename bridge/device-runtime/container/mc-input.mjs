#!/usr/bin/env node
// Human-like pointer input for the desktop's X display.
// Usage: mc-input move X Y W H | click X Y W H [left|right] | scroll X Y up|down N
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { path } from 'ghost-cursor'
import { overshoot } from 'ghost-cursor/lib/math.js'

const OVERSHOOT_THRESHOLD = 500
const OVERSHOOT_RADIUS = 120
const OVERSHOOT_SPREAD = 10
const PADDING = 0.25
const SCROLL_BOX = 20

const run = promisify(execFile)
const env = { ...process.env, DISPLAY: process.env.DISPLAY || ':20' }
const rand = (min, max) => min + Math.random() * (max - min)
const sleep = (min, max) => ['sleep', rand(min, max).toFixed(3)]

class UsageError extends Error {}

function numbers(args, count) {
  const values = args.map(Number)
  if (args.length !== count || !values.every(Number.isFinite)) throw new UsageError(`expected ${count} numbers`)
  return values
}

async function xdotool(args) {
  try {
    return (await run('xdotool', args, { env })).stdout
  } catch (error) {
    throw new Error(`xdotool failed: ${(error.stderr || error.message).trim()}`)
  }
}

async function pointer() {
  const fields = Object.fromEntries(
    (await xdotool(['getmouselocation', '--shell'])).split('\n').map((line) => line.split('=')),
  )
  const x = Number(fields.X)
  const y = Number(fields.Y)
  if (!Number.isFinite(x) || !Number.isFinite(y)) throw new Error('xdotool returned no pointer position')
  return { x, y }
}

function route(start, box) {
  const width = Math.max(1, box.w)
  const height = Math.max(1, box.h)
  const end = {
    x: box.x + width * (PADDING + Math.random() * (1 - 2 * PADDING)),
    y: box.y + height * (PADDING + Math.random() * (1 - 2 * PADDING)),
  }
  const target = { ...end, width, height }
  const points = Math.hypot(end.x - start.x, end.y - start.y) > OVERSHOOT_THRESHOLD
    ? (() => {
        const past = overshoot(end, OVERSHOOT_RADIUS)
        return [...path(start, past), ...path(past, target, OVERSHOOT_SPREAD)]
      })()
    : path(start, target)
  const out = []
  for (const point of [...points, end]) {
    const step = [Math.round(point.x), Math.round(point.y)]
    const last = out[out.length - 1]
    if (!last || last[0] !== step[0] || last[1] !== step[1]) out.push(step)
  }
  return out
}

async function move(box, after = []) {
  const steps = route(await pointer(), box).flatMap(([x, y]) => ['mousemove', String(x), String(y), ...sleep(0.004, 0.008)])
  await xdotool([...steps, ...after])
}

const [command, ...args] = process.argv.slice(2)
try {
  if (command === 'move') {
    const [x, y, w, h] = numbers(args, 4)
    await move({ x, y, w, h })
  } else if (command === 'click') {
    const button = { left: '1', right: '3', undefined: '1' }[args[4]]
    if (!button) throw new UsageError('button must be left or right')
    const [x, y, w, h] = numbers(args.slice(0, 4), 4)
    await move({ x, y, w, h }, [...sleep(0.05, 0.15), 'mousedown', button, ...sleep(0.06, 0.12), 'mouseup', button])
  } else if (command === 'scroll') {
    const wheel = { up: '4', down: '5' }[args[2]]
    if (!wheel) throw new UsageError('direction must be up or down')
    const [x, y, count] = numbers([args[0], args[1], args[3]], 3)
    if (!Number.isInteger(count) || count < 1) throw new UsageError('N must be a positive integer')
    const notches = Array.from({ length: count }, () => ['click', wheel, ...sleep(0.01, 0.03)]).flat()
    await move({ x: x - SCROLL_BOX / 2, y: y - SCROLL_BOX / 2, w: SCROLL_BOX, h: SCROLL_BOX }, notches)
  } else {
    throw new UsageError('usage: mc-input move X Y W H | click X Y W H [left|right] | scroll X Y up|down N')
  }
} catch (error) {
  process.stderr.write(`mc-input: ${error.message}\n`)
  process.exit(error instanceof UsageError ? 2 : 1)
}
