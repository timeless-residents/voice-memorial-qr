# voice-memorial-qr
Revolutionary voice-to-QR technology for eternal memory preservation

# 🎵 Voice Memorial QR - 世界初ハイブリッド音声保存技術

URL + RAWデータ埋め込みハイブリッド技術による革命的音声永続保存システム

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

## 🛠 開発・デプロイ

### ローカル開発
```bash
git clone <repository>
cd voice-memorial-qr
pip install -r requirements.txt
python app.py
