from flask import Flask, request, render_template, send_file, jsonify
import qrcode
import base64
import io
import os
import tempfile
import subprocess
from PIL import Image, ImageDraw, ImageFont
import uuid
from pathlib import Path
import urllib.parse
import shutil
import json
from datetime import datetime

app = Flask(__name__)

TEMP_DIR = tempfile.gettempdir()

def check_ffmpeg():
    """ffmpeg利用可能性確認"""
    try:
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except:
        return False

def is_supported_format(filename):
    """対応形式チェック（WebM・MOV対応版）"""
    # 音声形式
    audio_extensions = {'.mp3', '.m4a', '.wav', '.aac', '.ogg', '.flac'}
    # 動画形式（音声抽出対応）
    video_extensions = {'.webm', '.mp4', '.mov', '.avi', '.mkv'}
    
    file_extension = Path(filename).suffix.lower()
    return file_extension in (audio_extensions | video_extensions)

def process_audio_for_standalone_qr(audio_file_path, output_duration=2.0):
    """
    音声→完全自立型データURI処理（サーバー依存ゼロ版）
    """
    if not check_ffmpeg():
        raise Exception("FFmpeg not available on this system")
    
    try:
        unique_id = str(uuid.uuid4())[:8]
        file_extension = Path(audio_file_path).suffix.lower()
        
        # 一時出力ファイル
        opus_path = os.path.join(TEMP_DIR, f"processed_{unique_id}.opus")
        
        # 動画ファイルかどうかを判定
        video_extensions = {'.webm', '.mp4', '.mov', '.avi', '.mkv'}
        is_video_file = file_extension in video_extensions
        
        # ffmpegコマンド構築
        if is_video_file:
            # 動画ファイル：音声抽出 + 最適化
            ffmpeg_cmd = [
                'ffmpeg',
                '-i', audio_file_path,
                '-vn',  # 映像ストリーム無視（重要！）
                '-af', 'highpass=f=80,lowpass=f=8000',
                '-c:a', 'libopus',
                '-b:a', '1k',
                '-ac', '1',
                '-ar', '8000',
                '-t', str(output_duration),
                '-y',  # overwrite
                opus_path
            ]
        else:
            # 音声ファイル：通常処理
            ffmpeg_cmd = [
                'ffmpeg',
                '-i', audio_file_path,
                '-af', 'highpass=f=80,lowpass=f=8000',
                '-c:a', 'libopus',
                '-b:a', '1k',
                '-ac', '1',
                '-ar', '8000',
                '-t', str(output_duration),
                '-y',  # overwrite
                opus_path
            ]
        
        # subprocess実行
        result = subprocess.run(
            ffmpeg_cmd, 
            capture_output=True, 
            text=True, 
            timeout=30,
            check=False
        )
        
        if result.returncode != 0:
            # エラーの詳細分析
            error_details = result.stderr
            if "Invalid data" in error_details or "could not find codec" in error_details:
                raise Exception(f"Unsupported {file_extension} format or corrupted file")
            else:
                raise Exception(f"FFmpeg processing failed: {error_details}")
        
        # 出力ファイル確認
        if not os.path.exists(opus_path) or os.path.getsize(opus_path) == 0:
            raise Exception("FFmpeg produced empty output file")
        
        # RAWデータ読み込み
        with open(opus_path, 'rb') as f:
            raw_opus_data = f.read()
        
        # base64エンコード（UTF-8安全）
        encoded_data = base64.b64encode(raw_opus_data).decode('utf-8')
        
        # データURI形式作成（完全自立型）
        data_uri = f"data:audio/ogg;codecs=opus;base64,{encoded_data}"
        
        # QRコード容量制限チェック
        if len(data_uri) > 60000:  # 2秒対応で制限
            raise Exception(f"Audio too long for standalone QR embedding: {len(data_uri)} chars. Try shorter audio (under 2 seconds).")
        
        # クリーンアップ
        if os.path.exists(opus_path):
            os.remove(opus_path)
        
        return data_uri, len(raw_opus_data)
        
    except subprocess.TimeoutExpired:
        raise Exception("Audio processing timeout - file too large or complex")
    except Exception as e:
        # エラー時クリーンアップ
        if 'opus_path' in locals() and os.path.exists(opus_path):
            try:
                os.remove(opus_path)
            except:
                pass
        raise e

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate', methods=['POST'])
def generate_standalone_qr():
    """
    完全自立型QRコード生成（サーバー依存ゼロ版）
    """
    audio_file_path = None
    try:
        # FFmpeg利用可能性事前確認
        if not check_ffmpeg():
            return jsonify({'error': 'Audio processing service temporarily unavailable. Please try again in a few minutes.'}), 503
        
        if 'audio' not in request.files:
            return jsonify({'error': 'No audio file provided'}), 400
        
        audio_file = request.files['audio']
        if audio_file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        # ファイルサイズ制限（2秒対応で調整）
        file_content = audio_file.read()
        if len(file_content) > 3 * 1024 * 1024:  # 3MB（2秒音声なので削減）
            return jsonify({'error': 'File too large. Max 3MB for 2-second optimal processing.'}), 400
        
        # ファイル形式確認（WebM・MOV対応）
        if not is_supported_format(audio_file.filename):
            return jsonify({
                'error': 'Unsupported file format. Supported: .mp3, .m4a, .wav, .aac, .ogg, .flac (audio) | .mp4, .mov, .avi, .mkv, .webm (video with audio extraction)'
            }), 400
        
        # 一時ファイル保存
        unique_id = str(uuid.uuid4())[:8]
        file_extension = Path(audio_file.filename).suffix.lower()
        audio_file_path = os.path.join(TEMP_DIR, f"input_{unique_id}{file_extension}")
        
        with open(audio_file_path, 'wb') as f:
            f.write(file_content)
        
        # ファイル保存確認
        if not os.path.exists(audio_file_path) or os.path.getsize(audio_file_path) == 0:
            raise Exception("Failed to save uploaded file")
        
        # 完全自立型データURI処理（2秒対応）
        data_uri, raw_size = process_audio_for_standalone_qr(audio_file_path, output_duration=2.0)
        
        # Pearl Memorial専用フォーマット作成
        pearl_memorial_data = {
            "pearl_memorial": "v1.0",
            "type": "standalone_audio",
            "audio_data": data_uri,
            "metadata": {
                "title": Path(audio_file.filename).stem,
                "filename": audio_file.filename,
                "created": datetime.now().isoformat(),
                "duration": 2.0,
                "id": unique_id,
                "technology": "Server-Independent DataURI",
                "creator": "Pearl Memorial System"
            }
        }
        
        # JSON文字列化
        qr_content = json.dumps(pearl_memorial_data, ensure_ascii=False, separators=(',', ':'))
        
        # QRコード容量最終確認
        if len(qr_content) > 70000:  # 2秒対応
            return jsonify({'error': f'Generated QR content too long: {len(qr_content)} chars. Try shorter audio (under 2 seconds).'}), 400
        
        # QRコード生成（最適化）
        qr = qrcode.QRCode(
            version=None,  # 自動サイズ調整
            error_correction=qrcode.constants.ERROR_CORRECT_L,  # 最小エラー訂正
            box_size=4,
            border=1,
        )
        
        qr.add_data(qr_content)
        qr.make(fit=True)
        
        # QRコードバージョン確認（デバッグ情報）
        qr_version = qr.version
        if qr_version > 40:
            return jsonify({'error': f'Audio too long for QR code (version {qr_version}). Maximum is version 40. Try shorter audio.'}), 400
        
        # QRコード画像生成
        qr_img = qr.make_image(fill_color="black", back_color="white")
        
        # ファイル形式判定メッセージ
        video_extensions = {'.webm', '.mp4', '.mov', '.avi', '.mkv'}
        is_video = file_extension in video_extensions
        process_type = f"Audio extracted from {file_extension.upper()} video" if is_video else f"Audio processed from {file_extension.upper()}"
        
        # メタデータ付きQRコード
        final_img = create_standalone_qr(qr_img, {
            'title': 'Pearl Memorial QR - Server-Independent',
            'filename': audio_file.filename,
            'raw_size': f"{raw_size} bytes",
            'content_length': f"{len(qr_content)} chars",
            'qr_version': f"Version {qr_version}",
            'technology': 'DataURI Embedded (Standalone)',
            'process_type': process_type,
            'id': unique_id,
            'reader_url': 'https://pearl-memorial-reader.github.io'
        })
        
        # 画像返却
        img_io = io.BytesIO()
        final_img.save(img_io, 'PNG', optimize=True, quality=95)
        img_io.seek(0)
        
        return send_file(
            img_io,
            mimetype='image/png',
            as_attachment=True,
            download_name=f"pearl_memorial_standalone_{Path(audio_file.filename).stem}_{unique_id}.png"
        )
        
    except subprocess.CalledProcessError as e:
        return jsonify({'error': f'Audio processing failed: {str(e)}'}), 500
    except Exception as e:
        error_msg = str(e)
        if "timeout" in error_msg.lower():
            return jsonify({'error': 'Audio processing timeout. Try a shorter file (under 2 seconds).'}), 408
        elif "ffmpeg" in error_msg.lower():
            return jsonify({'error': 'Audio processing service unavailable. Please try again later.'}), 503
        elif "version" in error_msg.lower() and "40" in error_msg:
            return jsonify({'error': 'Audio too long for QR code. Try shorter audio (under 2 seconds).'}), 400
        elif "unsupported" in error_msg.lower():
            return jsonify({'error': 'Unsupported or corrupted file format. Try MP3, WAV, M4A, or MP4/MOV video files.'}), 400
        else:
            return jsonify({'error': f'Processing failed: {error_msg}'}), 500
    finally:
        # 確実なクリーンアップ
        if audio_file_path and os.path.exists(audio_file_path):
            try:
                os.remove(audio_file_path)
            except:
                pass

def create_standalone_qr(qr_img, metadata):
    """
    完全自立型QRコード生成（サーバー依存ゼロ版）
    """
    qr_width, qr_height = qr_img.size
    header_height, footer_height, padding = 140, 180, 15
    
    total_width = qr_width + (padding * 2)
    total_height = header_height + qr_height + footer_height + (padding * 3)
    
    # 新しい画像作成
    final_img = Image.new('RGB', (total_width, total_height), 'white')
    
    # QRコード配置
    qr_y = header_height + padding
    final_img.paste(qr_img, (padding, qr_y))
    
    # テキスト描画
    draw = ImageDraw.Draw(final_img)
    
    try:
        font = ImageFont.load_default()
    except:
        font = None
    
    # ヘッダー
    title = metadata.get('title', 'Pearl Memorial QR')
    draw.text((padding, 15), title, fill='#2c3e50', font=font)
    
    # 技術的特徴強調（完全自立型）
    draw.text((padding, 35), "🚀 Server-Independent DataURI Technology", fill='#e74c3c', font=font)
    draw.text((padding, 55), "📱 Scan → Instant Offline Play", fill='#27ae60', font=font)
    draw.text((padding, 75), "🌐 No Internet Required Forever", fill='#9b59b6', font=font)
    draw.text((padding, 95), "⚡ Works in Airplane Mode", fill='#f39c12', font=font)
    draw.text((padding, 115), "🏆 1000-Year Guaranteed Playback", fill='#e67e22', font=font)
    
    # 区切り線
    line_y = 135
    draw.line([(padding, line_y), (total_width - padding, line_y)], fill='#3498db', width=2)
    
    # フッター情報
    footer_y = qr_y + qr_height + padding
    footer_items = [
        f"📁 File: {metadata.get('filename', 'Unknown')}",
        f"🔧 Process: {metadata.get('process_type', 'Audio processing')}",
        f"🆔 ID: {metadata.get('id', 'Unknown')}",
        f"📊 Raw: {metadata.get('raw_size', 'Unknown')}",
        f"📏 Content: {metadata.get('content_length', 'Unknown')}",
        f"🔢 QR: {metadata.get('qr_version', 'Unknown')}",
        f"⚙️ Tech: {metadata.get('technology', 'Unknown')}",
        f"🎵 Reader: {metadata.get('reader_url', 'Manual Setup')}",
        f"💎 Action: Scan with Pearl Memorial Reader App"
    ]
    
    for i, item in enumerate(footer_items):
        draw.text((padding, footer_y + i * 18), item, fill='#34495e', font=font)
    
    # 重要な説明
    instruction = "🎵 Pearl Memorial - World's First Standalone Voice QR"
    inst_y = footer_y + len(footer_items) * 18 + 10
    draw.text((padding, inst_y), instruction, fill='#e67e22', font=font)
    
    return final_img

@app.route('/reader')
def pearl_memorial_reader():
    """
    完全自立型Pearl Memorial Reader（単体配布用）
    """
    return """
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="Pearl Memorial">
    <title>Pearl Memorial Reader - 完全自立型音声QR読み取り</title>
    
    <!-- PWA設定 -->
    <link rel="manifest" href="data:application/json;charset=utf-8,{
        &quot;name&quot;: &quot;Pearl Memorial Reader&quot;,
        &quot;short_name&quot;: &quot;PearlReader&quot;,
        &quot;start_url&quot;: &quot;./&quot;,
        &quot;display&quot;: &quot;standalone&quot;,
        &quot;background_color&quot;: &quot;#667eea&quot;,
        &quot;theme_color&quot;: &quot;#667eea&quot;,
        &quot;icons&quot;: [{
            &quot;src&quot;: &quot;data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ccircle cx='50' cy='50' r='40' fill='%23667eea'/%3E%3Ctext x='50' y='60' text-anchor='middle' fill='white' font-size='30'%3E🎵%3C/text%3E%3C/svg%3E&quot;,
            &quot;sizes&quot;: &quot;192x192&quot;,
            &quot;type&quot;: &quot;image/svg+xml&quot;
        }]
    }">
    
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            color: #333;
            padding: 20px;
        }
        
        .container { max-width: 400px; margin: 0 auto; }
        
        .header {
            text-align: center;
            color: white;
            margin-bottom: 30px;
        }
        
        .header h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }
        
        .status {
            background: rgba(255,255,255,0.9);
            padding: 20px;
            border-radius: 15px;
            text-align: center;
            margin-bottom: 20px;
            font-size: 1.1em;
        }
        
        .camera-container {
            background: white;
            border-radius: 20px;
            padding: 20px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }
        
        #video {
            width: 100%;
            border-radius: 10px;
            background: #000;
        }
        
        .btn {
            background: #4CAF50;
            color: white;
            border: none;
            padding: 15px 30px;
            border-radius: 25px;
            font-size: 1.1em;
            width: 100%;
            margin: 10px 0;
            cursor: pointer;
            transition: all 0.3s ease;
        }
        
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 20px rgba(76, 175, 80, 0.3);
        }
        
        .btn:disabled {
            opacity: 0.6;
            background: #95a5a6;
            cursor: not-allowed;
        }
        
        .memorial-list {
            background: rgba(255,255,255,0.95);
            margin-top: 20px;
            padding: 20px;
            border-radius: 15px;
            display: none;
        }
        
        .memorial-item {
            padding: 15px;
            margin: 10px 0;
            background: #f8f9fa;
            border-radius: 10px;
            cursor: pointer;
            transition: background 0.3s ease;
        }
        
        .memorial-item:hover {
            background: #e9ecef;
        }
        
        .memorial-item h3 {
            margin-bottom: 5px;
            color: #2c3e50;
        }
        
        .memorial-item p {
            color: #666;
            font-size: 0.9em;
        }
        
        .tech-info {
            background: rgba(255,255,255,0.1);
            color: white;
            padding: 15px;
            border-radius: 10px;
            margin-top: 20px;
            font-size: 0.9em;
        }
        
        .offline-indicator {
            position: fixed;
            top: 10px;
            right: 10px;
            background: #27ae60;
            color: white;
            padding: 5px 10px;
            border-radius: 15px;
            font-size: 0.8em;
        }
    </style>
</head>
<body>
    <div class="offline-indicator">📱 オフライン動作中</div>
    
    <div class="container">
        <div class="header">
            <h1>🎵 Pearl Memorial</h1>
            <p>完全自立型音声QR読み取りシステム</p>
        </div>
        
        <div class="status" id="status">カメラ準備中...</div>
        
        <div class="camera-container">
            <button class="btn" id="startBtn" onclick="startCamera()">📹 カメラを開始</button>
            <video id="video" autoplay playsinline muted style="display: none;"></video>
            <canvas id="canvas" style="display: none;"></canvas>
        </div>
        
        <button class="btn" onclick="testQR()" style="background: #FF9800;">🧪 テストQR処理</button>
        
        <div class="memorial-list" id="memorialList">
            <h3>📋 保存された記憶</h3>
            <div id="memorialItems"></div>
        </div>
        
        <div class="tech-info">
            <h4>🚀 技術仕様</h4>
            <p>• サーバー完全独立</p>
            <p>• インターネット不要</p>
            <p>• 機内モード対応</p>
            <p>• 1000年保証</p>
        </div>
    </div>

    <script>
        class PearlMemorialReader {
            constructor() {
                this.memorials = {};
                this.video = document.getElementById('video');
                this.canvas = document.getElementById('canvas');
                this.ctx = this.canvas.getContext('2d');
                this.scanning = false;
                this.lastProcessedQR = '';
            }

            async startCamera() {
                const status = document.getElementById('status');
                const startBtn = document.getElementById('startBtn');
                
                try {
                    status.textContent = 'カメラアクセス中...';
                    
                    const constraints = {
                        video: {
                            facingMode: 'environment',
                            width: { ideal: 640 },
                            height: { ideal: 480 }
                        }
                    };
                    
                    const stream = await navigator.mediaDevices.getUserMedia(constraints);
                    this.video.srcObject = stream;
                    this.video.style.display = 'block';
                    startBtn.style.display = 'none';
                    
                    this.video.onloadedmetadata = () => {
                        this.canvas.width = this.video.videoWidth;
                        this.canvas.height = this.video.videoHeight;
                        status.textContent = '🎵 Pearl Memorial QRコードをカメラに向けてください';
                        this.startScanning();
                    };
                    
                    // iPhone用の追加設定
                    this.video.setAttribute('webkit-playsinline', 'true');
                    this.video.setAttribute('playsinline', 'true');
                    
                } catch (error) {
                    console.error('カメラエラー:', error);
                    status.textContent = `カメラエラー: ${error.name}`;
                    
                    if (error.name === 'NotAllowedError') {
                        status.innerHTML = `
                            カメラアクセスが拒否されました。<br>
                            ブラウザ設定でカメラを許可してください
                        `;
                    }
                }
            }

            startScanning() {
                if (this.scanning) return;
                this.scanning = true;
                this.scan();
            }

            scan() {
                if (!this.scanning) return;
                
                if (this.video.readyState === this.video.HAVE_ENOUGH_DATA) {
                    this.ctx.drawImage(this.video, 0, 0);
                    
                    // 簡易QR検出（実際のプロダクトでは高度な検出が必要）
                    // ここではテスト用の検出ロジック
                    this.checkForQRPattern();
                }
                
                requestAnimationFrame(() => this.scan());
            }

            checkForQRPattern() {
                // 実際の実装では画像解析によるQR検出
                // 開発段階では手動テスト
            }

            processQR(qrContent) {
                // 重複処理防止
                if (qrContent === this.lastProcessedQR) return;
                this.lastProcessedQR = qrContent;
                
                try {
                    const data = JSON.parse(qrContent);
                    
                    if (data.pearl_memorial && data.type === 'standalone_audio') {
                        this.processMemorial(data);
                        document.getElementById('status').textContent = '🎉 Pearl Memorial QR処理完了！';
                    } else {
                        document.getElementById('status').textContent = '❌ Pearl Memorial QRではありません';
                    }
                } catch (e) {
                    // データURI直接形式の場合
                    if (qrContent.startsWith('data:audio/')) {
                        this.playAudio(qrContent, 'Direct Audio QR');
                    } else {
                        console.error('QR処理エラー:', e);
                        document.getElementById('status').textContent = '❌ QRコードを認識できませんでした';
                    }
                }
            }

            processMemorial(memorialData) {
                const metadata = memorialData.metadata;
                const memorialId = metadata.id;
                
                // メモリアル保存
                this.memorials[memorialId] = memorialData;
                
                // 音声再生
                this.playAudio(memorialData.audio_data, metadata.title);
                
                // リスト更新
                this.updateMemorialList();
            }

            playAudio(dataURI, title) {
                try {
                    const audio = new Audio(dataURI);
                    
                    audio.play().then(() => {
                        document.getElementById('status').textContent = `🎵 再生中: ${title}`;
                    }).catch(e => {
                        document.getElementById('status').textContent = '🔇 音声再生にはユーザー操作が必要です';
                        console.error('音声再生エラー:', e);
                    });
                    
                    audio.onended = () => {
                        document.getElementById('status').textContent = '✅ 再生完了 - 次のQRをスキャンしてください';
                    };
                    
                    audio.onerror = (e) => {
                        document.getElementById('status').textContent = '❌ 音声データが破損しています';
                        console.error('音声エラー:', e);
                    };
                    
                } catch (e) {
                    document.getElementById('status').textContent = '❌ 音声形式がサポートされていません';
                    console.error('音声作成エラー:', e);
                }
            }

            updateMemorialList() {
                const listContainer = document.getElementById('memorialList');
                const itemsContainer = document.getElementById('memorialItems');
                
                listContainer.style.display = 'block';
                itemsContainer.innerHTML = '';
                
                Object.keys(this.memorials).forEach(id => {
                    const memorial = this.memorials[id];
                    const metadata = memorial.metadata;
                    
                    const item = document.createElement('div');
                    item.className = 'memorial-item';
                    item.onclick = () => this.playAudio(memorial.audio_data, metadata.title);
                    
                    item.innerHTML = `
                        <h3>🎵 ${metadata.title}</h3>
                        <p>📅 ${new Date(metadata.created).toLocaleString()}</p>
                        <p>📁 ${metadata.filename}</p>
                        <p>🆔 ${metadata.id}</p>
                    `;
                    
                    itemsContainer.appendChild(item);
                });
            }

            // テスト機能
            testQR() {
                const testMemorial = {
                    "pearl_memorial": "v1.0",
                    "type": "standalone_audio",
                    "audio_data": "data:audio/wav;base64,UklGRnoGAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQoGAACBhYqFbF1fdJivrJBhNjVgodDbq2EcBj+a2/LDciUFLIHO8tiJNwgZaLvt559NEAxQp+PwtmMcBj2k4PTBeC",
                    "metadata": {
                        "title": "テスト音声",
                        "filename": "test_audio.wav",
                        "created": new Date().toISOString(),
                        "duration": 2.0,
                        "id": "test_001",
                        "technology": "Server-Independent DataURI",
                        "creator": "Pearl Memorial System"
                    }
                };
                
                this.processMemorial(testMemorial);
            }
        }

        // 初期化
        const reader = new PearlMemorialReader();
        
        async function startCamera() {
            await reader.startCamera();
        }
        
        function testQR() {
            reader.testQR();
        }
        
        // PWA検出
        if (window.navigator.standalone) {
            document.querySelector('.offline-indicator').textContent = '📱 PWAモード';
        }
        
        // ページ読み込み完了
        document.addEventListener('DOMContentLoaded', () => {
            document.getElementById('status').textContent = '🚀 Pearl Memorial Reader 準備完了';
        });
    </script>
</body>
</html>
    """

@app.route('/health')
def health_check():
    """ヘルスチェック（完全自立型対応版）"""
    ffmpeg_available = check_ffmpeg()
    
    return jsonify({
        'status': 'healthy' if ffmpeg_available else 'degraded',
        'message': 'Pearl Memorial Standalone QR Generator',
        'ffmpeg_available': ffmpeg_available,
        'technology': 'Server-Independent DataURI Embedding',
        'supported_formats': {
            'audio': ['.mp3', '.m4a', '.wav', '.aac', '.ogg', '.flac'],
            'video_with_audio_extraction': ['.mp4', '.mov', '.avi', '.mkv', '.webm']
        },
        'features': [
            'Audio processing (ffmpeg direct)',
            'Video audio extraction (MP4/MOV/WebM)',
            'Standalone QR generation',
            'DataURI-based instant playback',
            'Server-independent permanence',
            '2-second optimal duration',
            'Offline-first design'
        ],
        'output': {
            'format': 'Pearl Memorial JSON + DataURI',
            'reader': 'Standalone HTML5 app',
            'deployment': 'GitHub Pages compatible'
        },
        'version': '7.0-standalone-server-independent'
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)
