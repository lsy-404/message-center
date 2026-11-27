self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()))

self.addEventListener('push', (event) => {
  let data = {}
  try { data = event.data ? event.data.json() : {} } catch { data = {} }
  event.waitUntil(self.registration.showNotification(data.title || 'Message Center', {
    body: data.body || '',
    tag: data.tag || undefined,
    renotify: Boolean(data.tag),
    icon: '/icon-192.png',
    badge: '/icon-192.png',
    data: { conversationId: data.conversationId || null },
  }))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const conversationId = event.notification.data && event.notification.data.conversationId
  const target = conversationId ? `/app?conversation=${encodeURIComponent(conversationId)}` : '/app'
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    const open = windows.find((client) => new URL(client.url).origin === self.location.origin)
    if (open) {
      await open.focus()
      if (conversationId && 'navigate' in open) await open.navigate(target)
      return
    }
    await self.clients.openWindow(target)
  })())
})
