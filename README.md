# voice-memorial-qr
Revolutionary voice-to-QR technology for eternal memory preservation

# 🎵 Voice Memorial QR - 世界初ハイブリッド音声保存技術

URL + RAWデータ埋め込みハイブリッド技術による革命的音声永続保存システム

## 📍 Repository Information
- **GitHub URL**: https://github.com/timeless-residents/voice-memorial-qr
- **Production URL**: https://voice-memorial-qr.onrender.com
- **最終更新**: 2025-06-26 - メタデータ記録・読み込み機能の修正

## 🚀 革命的技術仕様

### ハイブリッド音声保存技術
- **ffmpeg subprocess直接実行**: 高品質音声圧縮
- **RAWデータ埋め込み**: URLパラメータに音声データ直接格納
- **サーバー不要永続性**: URLが残る限り音声データも永続
- **即座再生**: QRスキャン → ブラウザ起動 → 音声再生

### 技術スタック
- **バックエンド**: Python Flask + subprocess ffmpeg
- **音声処理**: FFmpeg (opus 1k 8khz 3sec)
- **QRコード**: qrcode library (最適化)
- **フロントエンド**: Vanilla JS (Cold Start対応)
- **デプロイ**: Render.com Free Tier対応

## ⚡ 特徴

- **瞬時再生**: QRスキャン → 自動音声再生
- **永続保存**: サーバー不要のRAWデータ埋め込み
- **簡単シェア**: URL共有でバイラル拡散
- **Cold Start対応**: Free Tierでも最適化されたUX
- **メタデータ完全対応**: タイトル、受取人、説明、感情レベル、特別な機会、位置情報を保存
- **ハイブリッドQR**: iPhone標準カメラ直接再生 + Reader経由フルメタデータ表示

## 🛠 開発・デプロイ

### ローカル開発
```bash
git clone https://github.com/timeless-residents/voice-memorial-qr.git
cd voice-memorial-qr
pip install -r requirements.txt
python app.py
```

### Render.comデプロイ
- render.yaml設定済み
- 環境変数不要（自動検出）
- FFmpeg自動インストール対応

## 📝 最近の更新履歴

### 2025-06-26: メタデータ機能修正
- ユーザー入力メタデータ（タイトル、受取人、説明、感情レベル、特別な機会）の記録・読み込み修正
- 位置情報データのJSON処理追加
- QRコード内のpearl_dataにすべてのメタデータを含めるよう改善
- データ喪失防止のための適切なエラーハンドリング実装

### 主要機能
- **メタデータ記録**: フォームから送信されたすべてのメタデータをQRコードに保存
- **ハイブリッドモード**: URLベース（iPhone直接再生）とJSONベース（フルメタデータ）の自動選択
- **位置情報対応**: 記録場所の緯度経度と住所情報を保存可能
- **永続保存**: DataURI形式で音声データをQRコード内に埋め込み

## 🔧 技術詳細

### app.py の主要コンポーネント
1. **`/generate` エンドポイント**: 
   - 音声ファイルとメタデータを受け取り、QRコードを生成
   - FFmpegで音声を最適化（Opus 1kbps, 8kHz, 最大2秒）
   - ユーザーメタデータを適切に抽出・保存

2. **`create_hybrid_qr` 関数**:
   - iPhone標準カメラ用URLとReader用JSONの両方に対応
   - サイズに基づいて最適な形式を自動選択
   - すべてのメタデータをpearl_data構造に含める

3. **`/play` エンドポイント**:
   - audioパラメータ: iPhone直接再生用
   - dataパラメータ: Reader経由のメタデータ付き再生用
