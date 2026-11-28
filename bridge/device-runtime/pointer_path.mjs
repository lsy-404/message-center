// Prints a human-like pointer path from ghost-cursor as JSON [[x, y], ...].
// Usage: node pointer_path.mjs <fromX> <fromY> <boxX> <boxY> <boxW> <boxH>
// The end point is a random spot inside the box, away from its edges; long moves overshoot and correct back,
// as ghost-cursor's own cursor does.
import { path } from 'ghost-cursor'
import { overshoot } from 'ghost-cursor/lib/math.js'

const OVERSHOOT_THRESHOLD = 500
const OVERSHOOT_RADIUS = 120
const OVERSHOOT_SPREAD = 10
const PADDING = 0.25

const [fromX, fromY, boxX, boxY, boxW, boxH] = process.argv.slice(2).map(Number)
if (![fromX, fromY, boxX, boxY, boxW, boxH].every(Number.isFinite)) {
  process.stderr.write('pointer_path: six numbers required\n')
  process.exit(2)
}
const width = Math.max(1, boxW)
const height = Math.max(1, boxH)
const start = { x: fromX, y: fromY }
const end = {
  x: boxX + width * (PADDING + Math.random() * (1 - 2 * PADDING)),
  y: boxY + height * (PADDING + Math.random() * (1 - 2 * PADDING)),
}
const target = { ...end, width, height }

const points = Math.hypot(end.x - start.x, end.y - start.y) > OVERSHOOT_THRESHOLD
  ? (() => {
      const past = overshoot(end, OVERSHOOT_RADIUS)
      return [...path(start, past), ...path(past, target, OVERSHOOT_SPREAD)]
    })()
  : path(start, target)

const out = []
for (const point of points) {
  const step = [Math.round(point.x), Math.round(point.y)]
  const last = out[out.length - 1]
  if (!last || last[0] !== step[0] || last[1] !== step[1]) out.push(step)
}
const final = [Math.round(end.x), Math.round(end.y)]
const last = out[out.length - 1]
if (!last || last[0] !== final[0] || last[1] !== final[1]) out.push(final)
process.stdout.write(JSON.stringify(out))
