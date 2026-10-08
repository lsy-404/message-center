const assert = require('node:assert/strict')
const { chromium } = require('F:/Development/lsy-404@CASSIE/node_modules/playwright')

async function main() {
  const browser = await chromium.launch({ headless: true })
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
        { id: 'image-message', direction: 'inbound', senderName: '测试联系人', body: '描述 [图片] 后续文字', contentType: 'text', occurredAt: new Date().toISOString(), attachments: [{ id: 'image-1', fileName: 'image.png', mimeType: 'image/png', downloadable: true }] },
        { id: 'text-message', direction: 'inbound', senderName: '测试联系人', body: '[图片]', contentType: 'text', occurredAt: new Date().toISOString(), attachments: [] },
        { id: 'pending-message', direction: 'inbound', senderName: '测试联系人', body: '[图片]', contentType: 'text', occurredAt: new Date().toISOString(), attachments: [{ id: 'pending-1', fileName: 'pending.png', mimeType: 'image/png', downloadable: false }] },
      ],
    }
    await page.route('**/api/inbox**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(payload) }))
    await page.route('**/api/files/image-1', (route) => route.fulfill({
      status: 200,
      contentType: 'image/png',
      body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/nWQAAAAASUVORK5CYII=', 'base64'),
    }))
    await page.goto('http://127.0.0.1:5173/', { waitUntil: 'networkidle' })

    assert.equal(await page.locator('.nav-section:first-child .nav-item').count(), 3, 'all + two channel entries')
    assert.equal(await page.locator('.management-nav .nav-item').count(), 1, 'one management entry')
    assert.equal(await page.locator('.nav-pane').evaluate((element) => element.textContent.includes('qq-account-1')), false, 'connector IDs stay out of navigation')

    await page.locator('.conversation-row').first().click()
    const imageBody = page.locator('.message-row').filter({ has: page.locator('img.attachment-image') }).locator('.message-bubble p')
    await imageBody.waitFor()
    assert.equal(await imageBody.textContent(), '描述 后续文字', 'remove only the image marker and preserve surrounding text')
    assert.equal(await page.locator('.message-row').nth(1).locator('.message-bubble p').textContent(), '[图片]', 'keep marker when there is no image attachment')
    assert.equal(await page.locator('.message-row').nth(2).locator('.message-bubble p').textContent(), '[图片]', 'keep marker for a pending image')
    assert.equal(await page.locator('.message-row').nth(2).locator('.attachment').textContent(), '▤pending.png等待上传')

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
