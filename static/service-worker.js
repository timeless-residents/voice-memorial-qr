const CACHE_NAME = "pearl-cache-v2";
const urlsToCache = [
  "/",
  "/play",
  "/reader",
  "/static/icon-192.png",
  "/static/icon-512.png",
  "/static/maskable-icon-512.png",
  "/static/manifest.json",
  "/static/service-worker.js",
  "/static/offline.html",
  "/generate"
];

// インストール：キャッシュ保存
self.addEventListener("install", event => {
  // 新しいサービスワーカーがすぐにアクティブになるようにする
  self.skipWaiting();

  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(urlsToCache))
      .catch(error => console.log('キャッシュの初期化に失敗:', error))
  );
});

// アクティベート：古いキャッシュを削除
self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.map(cacheName => {
          if (cacheName !== CACHE_NAME) {
            return caches.delete(cacheName);
          }
        })
      );
    }).then(() => {
      // 新しいサービスワーカーがすぐにページをコントロール
      return self.clients.claim();
    })
  );
});

// フェッチ：キャッシュファーストで、ネットワーク失敗時はキャッシュから
self.addEventListener("fetch", event => {
  event.respondWith(
    caches.match(event.request)
      .then(response => {
        if (response) {
          return response; // キャッシュヒット
        }

        // キャッシュになければネットワークにフェッチ
        return fetch(event.request)
          .then(netResponse => {
            // レスポンスが有効か確認（リダイレクトやエラーでない）
            if (!netResponse || netResponse.status !== 200 || netResponse.type !== 'basic') {
              return netResponse;
            }

            // レスポンスのクローンを作成（ストリームは一度しか使えないため）
            const responseToCache = netResponse.clone();

            // 動的にキャッシュに追加
            caches.open(CACHE_NAME)
              .then(cache => {
                cache.put(event.request, responseToCache);
              })
              .catch(error => console.log('動的キャッシュに失敗:', error));

            return netResponse;
          })
          .catch(error => {
            console.log('ネットワークリクエスト失敗:', error);

            // HTML リクエストの場合はオフラインページを返す
            if (event.request.headers && event.request.headers.get('Accept') && event.request.headers.get('Accept').includes('text/html')) {
              return caches.match('/static/offline.html')
                .then(response => {
                  if (response) {
                    return response;
                  }
                  // オフラインページがキャッシュになければ、単純なレスポンスを生成
                  const offlineHtml = `<!DOCTYPE html>
                  <html>
                  <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>オフラインです</title>
                    <style>
                      body { font-family: sans-serif; padding: 20px; text-align: center; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; height: 100vh; display: flex; align-items: center; justify-content: center; }
                      .container { background: white; color: #333; padding: 20px; border-radius: 10px; box-shadow: 0 4px 8px rgba(0,0,0,0.2); }
                      h1 { margin: 10px 0; }
                      button { background: #3498db; color: white; border: none; padding: 10px 20px; margin-top: 20px; border-radius: 5px; cursor: pointer; }
                    </style>
                  </head>
                  <body>
                    <div class="container">
                      <h1>📵 オフラインです</h1>
                      <p>インターネット接続が必要です。</p>
                      <button onclick="location.reload()">再接続を試みる</button>
                    </div>
                  </body>
                  </html>`;
                  return new Response(offlineHtml, { headers: { 'Content-Type': 'text/html' } });
                });
            }

            // 他のリソースの場合はフォールバック処理
            if (event.request.url.includes('/play')) {
              return caches.match('/play');
            } else if (event.request.url.includes('/reader')) {
              return caches.match('/reader');
            } else if (event.request.url.includes('/static/')) {
              // 静的リソース（アイコンなど）
              const url = new URL(event.request.url);
              const fileName = url.pathname.split('/').pop();
              // 汎用的なアイコンにフォールバック
              if (fileName.includes('icon')) {
                return caches.match('/static/icon-512.png');
              }
            }

            return caches.match('/static/offline.html');
          });
      })
  );
});
