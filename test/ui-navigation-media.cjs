const assert = require('node:assert/strict')
const { chromium } = require('playwright')

async function main() {
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH } : {}),
  })
  try {
    const page = await browser.newPage({ viewport: { width: 768, height: 1024 }, isMobile: true, hasTouch: true })
    const connectors = [
      { id: 'qq-account-1', kind: 'im', channelLabel: 'QQ', accountLabel: 'QQ 主账号', displayName: 'QQ', mode: 'cloud', state: 'online', capabilities: ['receive_text'] },
      { id: 'qq-account-2', kind: 'im', channelLabel: 'QQ', accountLabel: 'QQ 工作账号', displayName: 'QQ', mode: 'cloud', state: 'online', capabilities: ['receive_text'] },
      { id: 'wechat-account', kind: 'im', channelLabel: '微信', accountLabel: '微信账号', displayName: '微信', mode: 'cloud', state: 'online', capabilities: ['receive_text'] },
    ]
    const conversations = connectors.map((connector, index) => ({
      id: `conv-${index + 1}`,
      connectorId: connector.id,
      connectorKind: connector.kind,
      connectorChannelLabel: connector.channelLabel,
      title: `会话 ${index + 1}`,
      avatarLabel: '会',
      unreadCount: index === 2 ? 3 : 0,
      lastMessagePreview: '本地合成检查',
      lastMessageAt: new Date().toISOString(),
      connectorState: 'online',
      capabilities: ['receive_text'],
    }))
    const payload = {
      ok: true,
      selectedConversationId: 'conv-1',
      connectors,
      conversations,
      messages: [
        { id: 'image-message', direction: 'inbound', senderName: '林女士', senderAvatarPath: '/avatars/lin-v1.svg', body: '描述\n[图片]\n后续文字\n[图片]\n教程里写[图片]作为占位', contentType: 'text', occurredAt: new Date().toISOString(), attachments: [
          { id: 'image-loaded', fileName: 'image-loaded.gif', mimeType: 'image/gif', downloadable: true },
          { id: 'image-failed', fileName: 'image-failed.gif', mimeType: 'image/gif', downloadable: true },
        ] },
        { id: 'text-message', direction: 'inbound', senderName: '张三', senderAvatarPath: null, body: '[图片]', contentType: 'text', occurredAt: new Date().toISOString(), attachments: [] },
        { id: 'pending-message', direction: 'outbound', senderName: 'Bob Lee', senderAvatarPath: '/avatars/bob.svg', body: '[图片]', contentType: 'text', occurredAt: new Date().toISOString(), deliveryState: 'queued', attachments: [{ id: 'pending-1', fileName: 'pending.png', mimeType: 'image/png', downloadable: false }] },
        { id: 'failed-message', direction: 'outbound', senderName: 'Bob Lee', body: '失败消息', contentType: 'text', occurredAt: new Date().toISOString(), deliveryState: 'failed', attachments: [] },
        { id: 'uncertain-message', direction: 'outbound', senderName: 'Bob Lee', body: '待确认消息', contentType: 'text', occurredAt: new Date().toISOString(), deliveryState: 'uncertain', attachments: [] },
        { id: 'delivered-message', direction: 'outbound', senderName: 'Bob Lee', body: '已发送消息', contentType: 'text', occurredAt: new Date().toISOString(), deliveryState: 'delivered', attachments: [] },
        { id: 'inbound-state-message', direction: 'inbound', senderName: '张三', body: '入站消息', contentType: 'text', occurredAt: new Date().toISOString(), deliveryState: 'queued', authorRole: 'contact', agentRead: true, attachments: [] },
        { id: 'agent-message', direction: 'outbound', senderName: 'Agent', body: '代理回复', contentType: 'text', occurredAt: new Date().toISOString(), deliveryState: 'delivered', authorRole: 'agent', attachments: [] },
        { id: 'agent-unread-message', direction: 'inbound', senderName: '张三', body: '「李四：原文」\n- - - - - - - - - - - - - - -\n回复内容\n[小程序] 腾讯文档 · 排期表 · 腾讯文档', contentType: 'text', occurredAt: new Date().toISOString(), authorRole: 'contact', agentRead: false, attachments: [] },
        { id: 'qq-system-message', direction: 'inbound', senderName: 'hidden member alias', senderAvatarPath: '/avatars/hidden.svg', body: '一位新成员加入了群聊', presentation: 'system', contentType: 'text', occurredAt: new Date().toISOString(), attachments: [] },
        { id: 'unmarked-system-looking-message', direction: 'inbound', senderName: '普通成员', body: '这是一条普通消息', contentType: 'text', occurredAt: new Date().toISOString(), attachments: [] },
        { id: 'unmarked-placeholder-message', direction: 'inbound', senderName: '普通成员', body: '[类型:8]', contentType: 'text', occurredAt: new Date().toISOString(), attachments: [] },
      ],
    }
    let inboxRequestCount = 0
    await page.route('**/api/inbox**', (route) => {
      inboxRequestCount += 1
      const response = JSON.parse(JSON.stringify(payload))
      if (inboxRequestCount > 1) {
        response.messages[0].senderAvatarPath = '/avatars/lin-v2.svg'
        response.messages.find((message) => message.id === 'pending-message').deliveryState = 'delivered'
      }
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(response) })
    })
    await page.route('**/api/files/image-loaded', (route) => route.fulfill({
      status: 200,
      contentType: 'image/svg+xml',
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"><rect width="24" height="24" fill="#57a8d9"/></svg>',
    }))
    await page.route('**/api/files/image-failed', (route) => route.fulfill({ status: 404, body: 'missing' }))
    await page.route('**/avatars/**', (route) => route.fulfill({
      status: 200,
      contentType: 'image/svg+xml',
      body: route.request().url().includes('bob')
        ? '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40"><rect width="40" height="40" fill="#d9794e"/></svg>'
        : '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40"><rect width="40" height="40" fill="#5a82c8"/></svg>',
    }))
    const baseUrl = process.env.UI_TEST_URL || 'http://127.0.0.1:5173'
    await page.goto(`${baseUrl}/`, { waitUntil: 'networkidle' })

    const queuedRow = page.locator('.message-row[data-message-id="pending-message"]')
    assert.equal(await queuedRow.locator('.message-delivery-state').textContent(), '等待发送', 'queued outbound message is not presented as sent')
    assert.equal(await page.locator('.message-row[data-message-id="failed-message"] .message-delivery-state').textContent(), '发送失败')
    assert.equal(await page.locator('.message-row[data-message-id="uncertain-message"] .message-delivery-state').textContent(), '待确认（不可自动重发）')
    assert.equal(await page.locator('.message-row[data-message-id="delivered-message"] .message-delivery-state').textContent(), '已发送')
    assert.equal(await page.locator('.message-row[data-message-id="inbound-state-message"] .message-delivery-state').count(), 0, 'inbound messages do not show outbound delivery state')
    const agentRow = page.locator('.message-row[data-message-id="agent-message"]')
    assert.equal(await agentRow.getAttribute('data-author-role'), 'agent', 'agent replies expose their author role')
    assert.equal(await agentRow.locator('.message-sender').textContent(), 'AI 代理', 'agent replies are labelled as the AI agent')
    assert.equal(await agentRow.locator('.role-chip').textContent(), '代你发送')
    assert.equal(await agentRow.locator('.message-avatar img').count(), 0, 'agent replies use the agent avatar')
    assert.equal(await page.locator('.message-row[data-message-id="pending-message"] .role-chip').count(), 0, 'owner replies are not labelled as agent replies')
    assert.equal(await page.locator('.message-row[data-message-id="inbound-state-message"] .message-ai-read').textContent(), 'AI 已读')
    const unreadRow = page.locator('.message-row[data-message-id="agent-unread-message"]')
    assert.equal(await unreadRow.getAttribute('data-ai-read'), 'false')
    assert.equal(await unreadRow.locator('.message-ai-read').textContent(), 'AI 未读')
    assert.equal(await page.locator('.message-row[data-message-id="agent-message"] .message-ai-read').count(), 0, 'outbound messages do not show an AI read marker')
    assert.equal(await page.locator('.message-row[data-message-id="text-message"] .message-ai-read').count(), 0, 'messages outside the agent queue show no AI read marker')
    assert.match(await page.locator('.ai-unread-chip').textContent(), /AI 未读\s*1/)
    assert.equal(await unreadRow.locator('.block-quote .quote-author').textContent(), '李四')
    assert.equal(await unreadRow.locator('.block-quote .quote-text').textContent(), '原文')
    assert.equal(await unreadRow.locator('.block-text').textContent(), '回复内容')
    const card = unreadRow.locator('.block-card')
    assert.equal(await card.getAttribute('data-card-kind'), 'miniprogram')
    assert.equal(await card.locator('.card-title').textContent(), '腾讯文档')
    assert.equal(await card.locator('.card-summary').textContent(), '排期表')
    const systemRow = page.locator('.message-row[data-message-id="qq-system-message"]')
    assert.equal(await systemRow.getAttribute('data-presentation'), 'system')
    const systemNotice = systemRow.locator('.system-notice')
    assert.equal(await systemNotice.evaluate((element) => Array.from(element.childNodes)
      .filter((node) => node.nodeType === Node.TEXT_NODE).map((node) => node.textContent).join('').trim()),
    '一位新成员加入了群聊')
    assert.equal(await systemNotice.evaluate((element) => getComputedStyle(element).textAlign), 'center')
    assert.equal(await systemRow.locator('.message-avatar, .message-sender').count(), 0,
      'explicit QQ system rows hide member identity and avatar')
    for (const id of ['unmarked-system-looking-message', 'unmarked-placeholder-message']) {
      const ordinaryRow = page.locator(`.message-row[data-message-id="${id}"]`)
      assert.equal(await ordinaryRow.getAttribute('data-presentation'), null)
      assert.equal(await ordinaryRow.locator('.message-sender').count(), 1,
        'body text alone never selects system presentation')
    }
    assert.ok(await page.locator('.day-divider time[datetime]').count() >= 1, 'thread shows a dated day divider')
    const stamp = await page.locator('.message-row[data-message-id="text-message"] .message-meta time').getAttribute('datetime')
    assert.ok(!Number.isNaN(Date.parse(stamp)), 'message time exposes a machine-readable timestamp')

    assert.equal(await page.locator('.nav-section:first-child .nav-item').count(), 3, 'all + two channel entries')
    assert.equal(await page.locator('.management-nav .nav-item').count(), 1, 'one management entry')
    assert.equal(await page.locator('.nav-pane').evaluate((element) => element.textContent.includes('qq-account-1')), false, 'connector IDs stay out of navigation')

    await page.getByRole('button', { name: '刷新' }).click()
    await page.waitForFunction(() => document.querySelector('.message-row[data-message-id="pending-message"] .message-delivery-state')?.textContent === '已发送')
    await page.waitForFunction(() => document.querySelector('.message-row[data-message-id="image-message"] .message-avatar img')?.dataset.avatarPath === '/avatars/lin-v2.svg')
    await page.locator('.conversation-row').first().click()
    await page.locator('img.attachment-image').evaluateAll((images) => images.forEach((image) => { image.loading = 'eager' }))
    assert.ok(inboxRequestCount > 1, 'a refresh returned the updated sender avatar path')
    const aliceRow = page.locator('.message-row').filter({ hasText: '教程里写' })
    const aliceAvatar = aliceRow.locator('.message-avatar img')
    await aliceAvatar.waitFor()
    assert.match(await aliceAvatar.getAttribute('src'), /lin-v2\.svg/, 'late sender avatar path replaces the prior path')
    await aliceAvatar.evaluate((image) => image.decode())
    const bobRow = page.locator('.message-row[data-message-id="pending-message"]')
    assert.match(await bobRow.locator('.message-avatar img').getAttribute('src'), /bob\.svg/, 'outbound messages show the sender avatar')
    assert.equal(await page.locator('.message-row').nth(1).locator('.message-avatar').textContent(), '张三', 'missing avatar uses sender initials')
    assert.equal(await page.locator('.message-row').nth(1).locator('.message-avatar img').count(), 0, 'conversation avatar is not substituted for a missing sender avatar')
    const inboundOrder = await aliceRow.evaluate((row) => {
      const avatar = row.querySelector('.message-avatar').getBoundingClientRect()
      const bubble = row.querySelector('.message-block').getBoundingClientRect()
      return avatar.right <= bubble.left
    })
    const outboundOrder = await bobRow.evaluate((row) => {
      const avatar = row.querySelector('.message-avatar').getBoundingClientRect()
      const bubble = row.querySelector('.message-block').getBoundingClientRect()
      return avatar.left >= bubble.right
    })
    assert.equal(inboundOrder, true, 'inbound avatar appears before the message')
    assert.equal(outboundOrder, true, 'outbound avatar appears after the message')
    await page.waitForFunction(() => {
      const image = Array.from(document.querySelectorAll('img.attachment-image')).find((item) => item.alt === 'image-loaded.gif')
      return image?.complete && image.naturalWidth > 0
    })
    await page.waitForFunction(() => {
      const image = Array.from(document.querySelectorAll('img.attachment-image')).find((item) => item.alt === 'image-failed.gif')
      return image?.complete && image.naturalWidth === 0
    })
    const bodyBlocks = (row) => row.locator('.message-bubble > :not(.attachment)').evaluateAll((items) => items.map((item) =>
      item.classList.contains('block-media') ? `[media:${item.textContent}]` : item.textContent))
    assert.deepEqual(await bodyBlocks(aliceRow), ['描述\n后续文字', '[media:图片]', '教程里写[图片]作为占位'], 'hide one standalone marker only after one image loads; keep the failed and literal markers')
    assert.deepEqual(await bodyBlocks(page.locator('.message-row').nth(1)), ['[media:图片]'], 'keep marker when there is no image attachment')
    assert.deepEqual(await bodyBlocks(page.locator('.message-row').nth(2)), ['[media:图片]'], 'keep marker for a pending image')
    assert.equal(await page.locator('.message-row').nth(2).locator('.attachment').textContent(), 'pending.png等待上传')
    if (process.env.UI_PREVIEW_OUTPUT) await page.screenshot({ path: process.env.UI_PREVIEW_OUTPUT, fullPage: true })

    await page.getByRole('button', { name: '返回收件箱' }).click()
    await page.getByRole('button', { name: '未读', exact: true }).click()
    assert.equal(await page.locator('.conversation-row').count(), 1, 'unread filter keeps only unread conversations')
    assert.equal(await page.locator('.conversation-row').getAttribute('data-unread-count'), '3')
    await page.getByRole('button', { name: '全部', exact: true }).click()
    assert.equal(await page.locator('.conversation-row').count(), 3, 'all filter restores every conversation')

    await page.getByRole('button', { name: '接入管理' }).click()
    assert.equal(await page.locator('.instance-card').count(), 3, 'management shows each account')
    await page.locator('.instance-card').filter({ hasText: 'QQ 工作账号' }).getByRole('button', { name: '查看此账号会话' }).click()
    assert.equal(await page.locator('.conversation-row').count(), 1, 'account selection filters conversations')
    assert.equal(await page.locator('.conversation-row').textContent().then((text) => text.includes('会话 2')), true)
    assert.equal(await page.locator('.nav-pane').evaluate((element) => element.textContent.includes('qq-account-2')), false, 'connector IDs stay out of navigation after account selection')
    console.log('UI navigation and image placeholder checks passed (synthetic fixture).')
  } finally {
    await browser.close()
  }
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})
