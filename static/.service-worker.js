const CACHE_NAME = "pearl-cache-v1";
const urlsToCache = [
  "/",
  "/play.html",
  "/reader.html",
];

// インストール：キャッシュ保存
self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(urlsToCache))
  );
});

// フェッチ：キャッシュから返す
self.addEventListener("fetch", event => {
  event.respondWith(
    caches.match(event.request)
      .then(response => response || fetch(event.request))
  );
});
