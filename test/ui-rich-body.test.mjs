import assert from 'node:assert/strict'
import test from 'node:test'
import { parseMessageBody, previewText } from '../cloudflare-worker/ui/src/rich-body.mjs'

test('adapter card tags become structured cards', () => {
  assert.deepEqual(parseMessageBody('[卡片] 周末活动报名 · 点击填写报名信息 · 活动助手'), [
    { type: 'card', kind: 'app', label: '卡片', title: '周末活动报名', summary: '点击填写报名信息', source: '活动助手' },
  ])
  assert.deepEqual(parseMessageBody('[卡片] 只有标题'), [
    { type: 'card', kind: 'app', label: '卡片', title: '只有标题', summary: '', source: '' },
  ])
  assert.deepEqual(parseMessageBody('[卡片]'), [
    { type: 'card', kind: 'app', label: '卡片', title: '', summary: '', source: '' },
  ])
})

test('native digest tags identify mini programs, links and forwarded chats', () => {
  assert.equal(parseMessageBody('[小程序]美团外卖')[0].kind, 'miniprogram')
  assert.equal(parseMessageBody('[小程序]美团外卖')[0].title, '美团外卖')
  assert.equal(parseMessageBody('[QQ小程序] 腾讯文档 · 项目排期表')[0].kind, 'miniprogram')
  assert.equal(parseMessageBody('[链接] 发布说明 · 本周更新 · 官方博客')[0].kind, 'link')
  assert.equal(parseMessageBody('[分享]一篇文章')[0].kind, 'link')
  assert.equal(parseMessageBody('[聊天记录] 群聊的聊天记录')[0].kind, 'forward')
  assert.equal(parseMessageBody('[位置] 人民广场')[0].label, '位置')
})

test('transfers, red packets and pats keep their details', () => {
  assert.deepEqual(parseMessageBody('[转账] ¥12.34 · Lunch · Received'), [
    { type: 'money', kind: 'transfer', label: '转账', amount: '¥12.34', summary: 'Lunch', status: 'Received' },
  ])
  assert.deepEqual(parseMessageBody('[红包]恭喜发财，大吉大利'), [
    { type: 'money', kind: 'redpacket', label: '红包', amount: '', summary: '恭喜发财，大吉大利', status: '' },
  ])
  assert.deepEqual(parseMessageBody('[拍一拍] 张三 拍了拍 李四'), [{ type: 'notice', kind: 'pat', text: '张三 拍了拍 李四' }])
})

test('quoted replies render as a quote followed by the reply', () => {
  assert.deepEqual(parseMessageBody('「张三：明天几点开会？」\n- - - - - - - - - - - - - - -\n下午三点'), [
    { type: 'quote', author: '张三', text: '明天几点开会？' },
    { type: 'text', text: '下午三点' },
  ])
  assert.deepEqual(parseMessageBody('收到\n- - - - - - - - - - - - - - -\n「李四：文件发你了\n第二行」'), [
    { type: 'quote', author: '李四', text: '文件发你了\n第二行' },
    { type: 'text', text: '收到' },
  ])
  assert.deepEqual(parseMessageBody('[引用] 王工: 接口文档已经更新了\n好的我看看'), [
    { type: 'quote', author: '王工', text: '接口文档已经更新了' },
    { type: 'text', text: '好的我看看' },
  ])
  assert.deepEqual(parseMessageBody('[reply:type-7]\n同意'), [
    { type: 'quote', author: '', text: '' },
    { type: 'text', text: '同意' },
  ])
})

test('element placeholders become media chips and unknown elements stay readable', () => {
  assert.deepEqual(parseMessageBody('[picture:a1]'), [{ type: 'media', kind: 'image', label: '图片' }])
  assert.deepEqual(parseMessageBody('[file:季度报告.pdf]'), [{ type: 'media', kind: 'file', label: '季度报告.pdf' }])
  assert.deepEqual(parseMessageBody('[file:asset]'), [{ type: 'media', kind: 'file', label: '文件' }])
  assert.deepEqual(parseMessageBody('[sticker:微笑]'), [{ type: 'media', kind: 'sticker', label: '微笑' }])
  assert.deepEqual(parseMessageBody('[voice:v1]'), [{ type: 'media', kind: 'voice', label: '语音' }])
  assert.deepEqual(parseMessageBody('[ark:type-10]'), [{ type: 'media', kind: 'unknown', label: '卡片消息' }])
  assert.deepEqual(parseMessageBody('[opaque:type-99]'), [{ type: 'media', kind: 'unknown', label: '暂不支持显示的消息' }])
  assert.deepEqual(parseMessageBody('[图片]'), [{ type: 'media', kind: 'image', label: '图片' }])
})

test('tags only count at the start of a line and plain text is preserved', () => {
  assert.deepEqual(parseMessageBody('教程里写[图片]作为占位'), [{ type: 'text', text: '教程里写[图片]作为占位' }])
  assert.deepEqual(parseMessageBody('[图片]后面还有字'), [{ type: 'text', text: '[图片]后面还有字' }])
  assert.deepEqual(parseMessageBody('[不认识的标签] 内容'), [{ type: 'text', text: '[不认识的标签] 内容' }])
  assert.deepEqual(parseMessageBody('第一行\n\n第三行'), [{ type: 'text', text: '第一行\n\n第三行' }])
  assert.deepEqual(parseMessageBody('描述\n[卡片] 标题\n后续'), [
    { type: 'text', text: '描述' },
    { type: 'card', kind: 'app', label: '卡片', title: '标题', summary: '', source: '' },
    { type: 'text', text: '后续' },
  ])
  assert.deepEqual(parseMessageBody(''), [])
  assert.deepEqual(parseMessageBody(null), [])
})

test('list previews summarize tagged messages on one line', () => {
  assert.equal(previewText('[卡片] 周末活动报名 · 点击填写 · 活动助手'), '[卡片] 周末活动报名')
  assert.equal(previewText('[小程序]美团外卖'), '[小程序] 美团外卖')
  assert.equal(previewText('[QQ小程序]腾讯文档'), '[小程序] 腾讯文档')
  assert.equal(previewText('[picture:a1]'), '[图片]')
  assert.equal(previewText('[file:报告.pdf]'), '[文件] 报告.pdf')
  assert.equal(previewText('[转账] ¥12.34 · Lunch · Received'), '[转账] ¥12.34')
  assert.equal(previewText('「张三：原文」\n- - - - - - - - - - - - - - -\n回复内容'), '回复内容')
  assert.equal(previewText('王工：[小程序]腾讯文档'), '王工：[小程序] 腾讯文档')
  assert.equal(previewText('普通文字\n第二行'), '普通文字 第二行')
  assert.equal(previewText(''), '')
})
