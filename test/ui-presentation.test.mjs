import assert from 'node:assert/strict'
import test from 'node:test'
import { filterConversations } from '../cloudflare-worker/ui/src/conversation-list.mjs'
import {
  AVATAR_TONE_COUNT,
  avatarTone,
  buildThreadEntries,
  channelGlyph,
  channelTone,
  formatDayLabel,
  formatListTime,
  formatRelativeAge,
} from '../cloudflare-worker/ui/src/presentation.mjs'

const now = new Date(2026, 9, 15, 14, 30)
const at = (day, hour, minute = 0) => new Date(2026, 9, day, hour, minute)

test('list times read as compact Chinese labels relative to now', () => {
  assert.equal(formatListTime(new Date(now.valueOf() - 20_000), now), '刚刚')
  assert.equal(formatListTime(at(15, 14, 5), now), '25 分钟前')
  assert.equal(formatListTime(at(15, 9, 7), now), '09:07')
  assert.equal(formatListTime(at(14, 23, 59), now), '昨天')
  assert.equal(formatListTime(at(12, 8), now), '周一')
  assert.equal(formatListTime(at(8, 8), now), '10月8日')
  assert.equal(formatListTime(new Date(2025, 11, 31, 8), now), '2025年12月31日')
  assert.equal(formatListTime('not a date', now), '')
  assert.equal(formatListTime(null, now), '')
})

test('relative ages describe connector activity', () => {
  assert.equal(formatRelativeAge(new Date(now.valueOf() - 30_000), now), '刚刚')
  assert.equal(formatRelativeAge(new Date(now.valueOf() - 5 * 60_000), now), '5 分钟前')
  assert.equal(formatRelativeAge(new Date(now.valueOf() - 3 * 3_600_000), now), '3 小时前')
  assert.equal(formatRelativeAge(new Date(now.valueOf() - 2 * 86_400_000), now), '2 天前')
  assert.equal(formatRelativeAge(new Date(now.valueOf() + 60_000), now), '刚刚', 'clock skew never reads as the future')
})

test('day labels name today, yesterday and older weekdays', () => {
  assert.equal(formatDayLabel(at(15, 1), now), '今天')
  assert.equal(formatDayLabel(at(14, 23), now), '昨天')
  assert.equal(formatDayLabel(at(13, 12), now), '10月13日 周二')
})

test('thread entries add day dividers and group a sender’s consecutive messages', () => {
  const messages = [
    { id: 'a', direction: 'inbound', senderName: '陈晓', occurredAt: at(14, 10).toISOString() },
    { id: 'b', direction: 'inbound', senderName: '陈晓', occurredAt: at(14, 10, 2).toISOString() },
    { id: 'c', direction: 'inbound', senderName: '陈晓', occurredAt: at(14, 10, 9).toISOString() },
    { id: 'd', direction: 'outbound', senderName: 'Agent', authorRole: 'agent', occurredAt: at(14, 10, 10).toISOString() },
    { id: 'e', direction: 'outbound', senderName: 'Agent', authorRole: 'owner', occurredAt: at(14, 10, 11).toISOString() },
    { id: 'f', direction: 'outbound', senderName: 'Agent', authorRole: 'owner', occurredAt: at(15, 9).toISOString() },
  ]
  const entries = buildThreadEntries(messages, now)
  assert.deepEqual(entries.map((entry) => entry.kind === 'day' ? entry.label : `${entry.key}:${entry.continuation}`), [
    '昨天', 'a:false', 'b:true', 'c:false', 'd:false', 'e:false', '今天', 'f:false',
  ])
  assert.equal(entries[0].dateTime, '2026-10-14')
})

test('tones are stable and channels keep their identity colors', () => {
  assert.equal(channelTone('QQ'), 'blue')
  assert.equal(channelTone('qq'), 'blue')
  assert.equal(channelTone('微信'), 'green')
  assert.equal(channelTone('邮箱'), 'amber')
  assert.equal(channelTone('Study IM'), channelTone('Study IM'))
  assert.equal(avatarTone('陈晓'), avatarTone(' 陈晓 '))
  for (const name of ['a', 'b', '陈晓', '项目协作群', '']) {
    const tone = avatarTone(name)
    assert.ok(Number.isInteger(tone) && tone >= 0 && tone < AVATAR_TONE_COUNT)
  }
  assert.equal(channelGlyph('QQ'), 'QQ')
  assert.equal(channelGlyph('微信'), '微')
  assert.equal(channelGlyph('webhook'), 'WE')
  assert.equal(channelGlyph(''), '?')
})

test('unread-only filtering composes with channel and search filters', () => {
  const rows = [
    { id: 'one', connectorId: 'a', connectorChannelLabel: 'QQ', title: '项目', unreadCount: 2 },
    { id: 'two', connectorId: 'a', connectorChannelLabel: 'QQ', title: '读书', unreadCount: 0 },
    { id: 'three', connectorId: 'b', connectorChannelLabel: '微信', title: '项目', unreadCount: 1 },
  ]
  assert.deepEqual(filterConversations(rows, { unreadOnly: true }).map(({ id }) => id), ['one', 'three'])
  assert.deepEqual(filterConversations(rows, { unreadOnly: true, channelLabel: 'qq' }).map(({ id }) => id), ['one'])
  assert.deepEqual(filterConversations(rows, { unreadOnly: true, query: '读书' }).map(({ id }) => id), [])
  assert.deepEqual(filterConversations(rows, { unreadOnly: false }).map(({ id }) => id), ['one', 'two', 'three'])
})
