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
      unreadCount: 0,
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
        { id: 'inbound-state-message', direction: 'inbound', senderName: '张三', body: '入站消息', contentType: 'text', occurredAt: new Date().toISOString(), deliveryState: 'queued', attachments: [] },
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
    const imageBody = aliceRow.locator('.message-bubble p')
    assert.equal(await imageBody.textContent(), '描述\n后续文字\n[图片]\n教程里写[图片]作为占位', 'hide one standalone marker only after one image loads; keep the failed and literal markers')
    assert.equal(await page.locator('.message-row').nth(1).locator('.message-bubble p').textContent(), '[图片]', 'keep marker when there is no image attachment')
    assert.equal(await page.locator('.message-row').nth(2).locator('.message-bubble p').textContent(), '[图片]', 'keep marker for a pending image')
    assert.equal(await page.locator('.message-row').nth(2).locator('.attachment').textContent(), '▤pending.png等待上传')
    if (process.env.UI_PREVIEW_OUTPUT) await page.screenshot({ path: process.env.UI_PREVIEW_OUTPUT, fullPage: true })

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
