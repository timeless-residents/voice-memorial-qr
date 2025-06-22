const CACHE_NAME = "pearl-cache-v3"; // バージョンアップ
const OFFLINE_URL = "/static/offline.html";

// 必須ファイルを完全キャッシュ
const ESSENTIAL_FILES = [
  "/",
  "/play",
  "/reader",
  "/static/icon-192.png",
  "/static/icon-512.png",
  "/static/maskable-icon-512.png",
  "/static/manifest.json",
  "/static/offline.html",
  OFFLINE_URL
];

// 事前にキャッシュすると良いがなくても動作するファイル
const OPTIONAL_FILES = [
  // スタイルシート、スクリプト、その他のリソース
  "/static/app.js",
  "/static/styles.css",
  // 再生機能に必要なリソース
  "/static/audio-player.js"
];

// 🚀 インストール：必須ファイルの確実キャッシュ
self.addEventListener("install", event => {
  console.log("[SW] Installing service worker...");
  
  // 新しいサービスワーカーをすぐにアクティブに
  self.skipWaiting();

  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(async cache => {
        console.log("[SW] Caching essential files...");

        // 必須ファイルを確実にキャッシュ（失敗した場合は例外）
        await cache.addAll(ESSENTIAL_FILES);
        console.log("[SW] ✅ All essential files cached successfully");

        // オプションファイルは個別にキャッシュ試行（失敗しても続行）
        if (OPTIONAL_FILES.length > 0) {
          console.log("[SW] Attempting to cache optional files...");

          const optionalCachePromises = OPTIONAL_FILES.map(url =>
            fetch(url)
              .then(response => {
                if (response.ok) {
                  cache.put(url, response);
                  console.log(`[SW] ✓ Optional file cached: ${url}`);
                } else {
                  console.log(`[SW] ⚠ Failed to fetch optional file: ${url}`);
                }
              })
              .catch(err => console.log(`[SW] ⚠ Error caching optional file: ${url}`, err))
          );

          // オプションファイルのキャッシュを試みるが、失敗してもインストールは続行
          try {
            await Promise.allSettled(optionalCachePromises);
            console.log("[SW] Optional files caching completed");
          } catch (error) {
            console.log("[SW] Some optional files could not be cached", error);
          }
        }

        // キャッシュされたエントリを確認
        const keys = await cache.keys();
        console.log(`[SW] 📊 Total cached entries: ${keys.length}`);
      })
      .catch(error => {
        console.error("[SW] ❌ Failed to cache essential files:", error);
        // エラーでもインストールを続行
        return Promise.resolve();
      })
  );
});

// 🎯 アクティベート：古いキャッシュ削除と即座制御
self.addEventListener("activate", event => {
  console.log("[SW] Activating service worker...");
  
  event.waitUntil(
    caches.keys()
      .then(cacheNames => {
        // 古いキャッシュを削除
        const deletePromises = cacheNames
          .filter(cacheName => cacheName !== CACHE_NAME)
          .map(cacheName => {
            console.log(`[SW] Deleting old cache: ${cacheName}`);
            return caches.delete(cacheName);
          });
        
        return Promise.all(deletePromises);
      })
      .then(() => {
        console.log("[SW] ✅ Cache cleanup completed");
        // すぐにページをコントロール
        return self.clients.claim();
      })
      .then(() => {
        console.log("[SW] ✅ Service worker activated and controlling pages");
      })
  );
});

// 🌐 フェッチ：堅牢なオフライン対応
self.addEventListener("fetch", event => {
  // Chrome拡張機能のリクエストは無視
  if (!event.request.url.startsWith('http')) {
    return;
  }

  event.respondWith(handleRequest(event.request));
});

// 🛠️ リクエスト処理の中核ロジック
async function handleRequest(request) {
  const url = new URL(request.url);

  // QR生成エンドポイントは常にオンライン接続が必要
  if (url.pathname === '/generate') {
    try {
      console.log(`[SW] 🔒 QR generation requires online connection: ${url.pathname}`);
      return await fetch(request);
    } catch (error) {
      console.log(`[SW] ❌ QR generation failed (offline): ${url.pathname}`);
      // QR生成失敗時は専用メッセージを返す
      if (request.headers.get('Accept')?.includes('text/html')) {
        return createQRGenerationOfflineResponse();
      } else {
        return new Response(JSON.stringify({
          error: 'QR生成にはオンライン接続が必要です',
          offline: true
        }), {
          status: 503,
          headers: { 'Content-Type': 'application/json' }
        });
      }
    }
  }

  try {
    // 1️⃣ キャッシュ優先チェック
    const cachedResponse = await caches.match(request);
    if (cachedResponse) {
      console.log(`[SW] ✅ Cache hit: ${url.pathname}`);
      return cachedResponse;
    }

    // 2️⃣ ネットワーク試行
    try {
      console.log(`[SW] 🌐 Network request: ${url.pathname}`);
      const networkResponse = await fetch(request);

      // 成功したレスポンスをキャッシュに追加
      if (networkResponse && networkResponse.status === 200 && networkResponse.type === 'basic') {
        const responseToCache = networkResponse.clone();

        // 動的コンテンツを積極的にキャッシュ
        caches.open(CACHE_NAME)
          .then(cache => {
            // URLパラメータを含むリクエストも完全にキャッシュ（音声データを含む）
            cache.put(request, responseToCache);
            console.log(`[SW] 💾 Cached dynamic content: ${url.pathname}`);
          })
          .catch(error => console.log("[SW] Cache update failed:", error));
      }

      return networkResponse;

    } catch (networkError) {
      console.log(`[SW] ❌ Network failed for ${url.pathname}:`, networkError.message);

      // 3️⃣ オフライン フォールバック戦略
      return handleOfflineFallback(request, url);
    }

  } catch (error) {
    console.error(`[SW] ❌ Request handling failed for ${url.pathname}:`, error);
    return handleOfflineFallback(request, url);
  }
}

// QR生成が失敗した場合の専用レスポンス
function createQRGenerationOfflineResponse() {
  const offlineHtml = `<!DOCTYPE html>
  <html lang="ja">
  <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>QR生成 - オフライン</title>
    <style>
      body {
        font-family: -apple-system, sans-serif;
        text-align: center;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        height: 100vh;
        margin: 0;
        display: flex;
        align-items: center;
        justify-content: center;
      }
      .container {
        background: white;
        padding: 30px;
        border-radius: 15px;
        box-shadow: 0 10px 30px rgba(0,0,0,0.2);
        max-width: 500px;
        width: 90%;
      }
      h1 { color: #e74c3c; }
      p { margin: 20px 0; line-height: 1.5; }
      .button {
        background: #3498db;
        color: white;
        padding: 10px 20px;
        border-radius: 30px;
        text-decoration: none;
        display: inline-block;
        margin-top: 20px;
        font-weight: bold;
      }
    </style>
  </head>
  <body>
    <div class="container">
      <h1>📵 オフラインモード</h1>
      <p>QRコードの生成にはオンライン接続が必要です。Wi-FiまたはモバイルデータをONにしてから再試行してください。</p>
      <p>既存のQRコードの閲覧・再生は可能です。</p>
      <a href="/" class="button">ホームに戻る</a>
    </div>
    <script>
      window.addEventListener('online', () => {
        window.location.reload();
      });
    </script>
  </body>
  </html>`;

  return new Response(offlineHtml, {
    headers: { 'Content-Type': 'text/html' }
  });
}

// 🚨 オフライン時のフォールバック処理
async function handleOfflineFallback(request, url) {
  console.log(`[SW] 🚨 Offline fallback for: ${url.pathname}`);
  
  // 📄 HTMLリクエストの場合
  if (request.headers.get('Accept')?.includes('text/html')) {
    return handleHTMLFallback(url);
  }
  
  // 🖼️ 画像リクエストの場合
  if (request.headers.get('Accept')?.includes('image/')) {
    return handleImageFallback();
  }
  
  // 📄 その他リソースの場合
  return handleResourceFallback(url);
}

// 📄 HTML フォールバック
async function handleHTMLFallback(url) {
  console.log(`[SW] 🔍 Handling HTML fallback for: ${url.pathname}`);

  // play.htmlのURLパラメータ付きリクエスト（audio, data）を処理
  if (url.pathname.includes('/play') && url.search) {
    console.log(`[SW] 🎵 Audio playback URL detected with params: ${url.search}`);

    // キャッシュ内の同じURLのエントリを検索
    const cache = await caches.open(CACHE_NAME);
    const cachedKeys = await cache.keys();

    // URLのパス部分が一致するキャッシュエントリを探す
    for (const key of cachedKeys) {
      const keyURL = new URL(key.url);

      // 同じパスでクエリパラメータも部分的に一致するものを探す
      if (keyURL.pathname === url.pathname && keyURL.search && keyURL.search.includes(url.search.substring(0, 20))) {
        console.log(`[SW] ✅ Found matching cached audio URL: ${keyURL.pathname}${keyURL.search.substring(0, 20)}...`);
        const cachedResponse = await cache.match(key);
        if (cachedResponse) return cachedResponse;
      }
    }

    // 特定のパラメータを含む場合は音声データURLとして処理
    if (url.searchParams.has('audio') || url.searchParams.has('data')) {
      console.log(`[SW] 📻 Attempting to serve basic player for audio`);
      // 基本的な再生ページを提供
      const playResponse = await caches.match('/play');
      if (playResponse) {
        console.log(`[SW] ✅ Serving basic player page`);
        return playResponse;
      }
    }
  }

  // 特定ページの代替キャッシュを試行
  const alternativePages = [
    { pattern: '/play', fallback: '/play' },
    { pattern: '/reader', fallback: '/reader' },
    { pattern: '/', fallback: '/' }
  ];

  for (const alt of alternativePages) {
    if (url.pathname.includes(alt.pattern)) {
      const altResponse = await caches.match(alt.fallback);
      if (altResponse) {
        console.log(`[SW] ✅ Alternative page served: ${alt.fallback}`);
        return altResponse;
      }
    }
  }

  // 専用オフラインページ
  const offlineResponse = await caches.match(OFFLINE_URL);
  if (offlineResponse) {
    console.log("[SW] ✅ Offline page served");
    return offlineResponse;
  }

  // 最終フォールバック：シンプルなオフラインHTML
  return createFallbackHTML();
}

// 🖼️ 画像 フォールバック  
async function handleImageFallback() {
  const iconResponse = await caches.match('/static/icon-512.png');
  if (iconResponse) {
    console.log("[SW] ✅ Fallback icon served");
    return iconResponse;
  }
  
  // 透明な1x1ピクセル画像を生成
  const transparentGif = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';
  return new Response(transparentGif, {
    headers: { 'Content-Type': 'image/gif' }
  });
}

// 📦 リソース フォールバック
async function handleResourceFallback(url) {
  // manifest.json の代替
  if (url.pathname.includes('manifest.json')) {
    const manifestResponse = await caches.match('/static/manifest.json');
    if (manifestResponse) return manifestResponse;
  }
  
  // その他のリソース：404レスポンス
  return new Response('Resource not available offline', {
    status: 404,
    statusText: 'Not Found'
  });
}

// 🆘 最終フォールバック：インラインHTML生成
function createFallbackHTML() {
  const fallbackHTML = `<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="theme-color" content="#2c3e50">
    <title>Pearl Memorial - オフライン</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
            color: #333;
        }
        .container {
            background: rgba(255, 255, 255, 0.95);
            border-radius: 25px;
            padding: 40px;
            text-align: center;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            max-width: 500px;
            width: 100%;
            animation: fadeIn 0.6s ease-out;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(30px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .icon { font-size: 4em; margin-bottom: 20px; }
        h1 { color: #2c3e50; margin-bottom: 20px; font-size: 1.8em; }
        .subtitle { color: #7f8c8d; margin-bottom: 30px; }
        .message {
            background: rgba(52, 152, 219, 0.1);
            color: #3498db;
            padding: 15px;
            border-radius: 10px;
            margin: 20px 0;
            font-weight: 500;
        }
        .btn {
            background: linear-gradient(135deg, #3498db 0%, #2980b9 100%);
            color: white;
            border: none;
            padding: 15px 30px;
            border-radius: 50px;
            font-size: 1.1em;
            font-weight: 600;
            cursor: pointer;
            margin: 10px;
            transition: all 0.3s ease;
        }
        .btn:hover { transform: translateY(-2px); }
        .links { margin-top: 20px; }
        .link {
            color: #3498db;
            text-decoration: none;
            padding: 10px;
            display: inline-block;
            margin: 5px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">🐚</div>
        <h1>Pearl Memorial</h1>
        <div class="subtitle">オフラインモード</div>
        
        <div class="message">
            ✈️ 機内モードでも動作中<br>
            キャッシュ済みコンテンツを利用できます
        </div>
        
        <button class="btn" onclick="window.location.reload()">
            🔄 再読み込み
        </button>
        
        <div class="links">
            <a href="/" class="link">🏠 ホーム</a>
            <a href="/reader" class="link">📱 Reader</a>
            <a href="/play" class="link">🎵 Player</a>
        </div>
    </div>
    
    <script>
        // オンライン復帰時の自動リロード
        window.addEventListener('online', () => {
            console.log('🌐 Online restored');
            window.location.reload();
        });
        
        // エラーハンドリング
        window.addEventListener('error', (e) => {
            console.log('⚠️ Page error in offline mode:', e.message);
        });
        
        console.log('🚨 Pearl Memorial - Complete Offline Mode');
    </script>
</body>
</html>`;

  return new Response(fallbackHTML, {
    headers: { 'Content-Type': 'text/html' }
  });
}

// 📱 PWA更新通知
self.addEventListener('message', event => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    console.log("[SW] 🔄 Skipping waiting and activating new service worker");
    self.skipWaiting();
  }
});

// 🚀 起動ログ
console.log("[SW] 🐚 Pearl Memorial Service Worker v3 - Complete Offline Support Loaded");
