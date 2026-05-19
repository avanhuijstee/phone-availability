self.addEventListener('push', (event) => {
  const data = event.data ? event.data.json() : {};
  event.waitUntil(
    clients.matchAll({ includeUncontrolled: true, type: 'window' }).then((allClients) => {
      const appVisible = allClients.some(c => c.visibilityState === 'visible');
      if (appVisible) return;
      return self.registration.showNotification(data.title || '📞 Beschikbaar!', {
        body: data.body || '',
        icon: '/static/android-chrome-192x192.png',
      });
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  event.waitUntil(clients.openWindow('/'));
});
