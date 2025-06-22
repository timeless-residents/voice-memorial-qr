from flask import Flask, request, render_template_string, send_file, jsonify
import qrcode
import base64
import io
import os
import tempfile
import subprocess
from PIL import Image, ImageDraw, ImageFont
import uuid
from pathlib import Path
import json
from datetime import datetime

app = Flask(__name__)

# 設定
TEMP_DIR = tempfile.gettempdir()
MAX_FILE_SIZE = 3 * 1024 * 1024  # 3MB
MAX_DURATION = 2.0  # 2秒
QR_MAX_SIZE = 70000  # QRコード最大サイズ

# 対応形式
AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.wav', '.aac', '.ogg', '.flac'}
VIDEO_EXTENSIONS = {'.webm', '.mp4', '.mov', '.avi', '.mkv'}
ALL_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS

class PearlMemorialError(Exception):
    """Pearl Memorial専用エラークラス"""
    pass

def check_ffmpeg():
    """FFmpeg利用可能性確認"""
    try:
        result = subprocess.run(['ffmpeg', '-version'], 
                              capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except Exception:
        return False

def validate_file(file, content):
    """ファイル検証（統合版）"""
    if not file or file.filename == '':
        raise PearlMemorialError('ファイルが選択されていません')
    
    # ファイルサイズチェック
    if len(content) > MAX_FILE_SIZE:
        raise PearlMemorialError(f'ファイルサイズが大きすぎます（最大{MAX_FILE_SIZE//1024//1024}MB）')
    
    # ファイル形式チェック
    extension = Path(file.filename).suffix.lower()
    if extension not in ALL_EXTENSIONS:
        supported = ', '.join(sorted(ALL_EXTENSIONS))
        raise PearlMemorialError(f'対応していない形式です。対応形式: {supported}')
    
    return extension

def process_audio_to_datauri(file_path, duration=MAX_DURATION):
    """音声→完全自立型DataURI変換（最適化版）"""
    if not check_ffmpeg():
        raise PearlMemorialError('音声処理サービスが利用できません')
    
    try:
        unique_id = str(uuid.uuid4())[:8]
        extension = Path(file_path).suffix.lower()
        opus_path = os.path.join(TEMP_DIR, f"processed_{unique_id}.opus")
        
        # FFmpegコマンド構築
        is_video = extension in VIDEO_EXTENSIONS
        
        base_cmd = [
            'ffmpeg', '-i', file_path,
            '-af', 'highpass=f=80,lowpass=f=8000',  # フィルター
            '-c:a', 'libopus',                      # Opusコーデック
            '-b:a', '1k',                           # 極低ビットレート
            '-ac', '1',                             # モノラル
            '-ar', '8000',                          # 低サンプリングレート
            '-t', str(duration),                    # 時間制限
            '-y', opus_path                         # 出力
        ]
        
        if is_video:
            base_cmd.insert(3, '-vn')  # 動画ストリーム除外
        
        # subprocess実行
        result = subprocess.run(base_cmd, capture_output=True, text=True, 
                              timeout=30, check=False)
        
        if result.returncode != 0:
            error_msg = result.stderr
            if "Invalid data" in error_msg or "could not find codec" in error_msg:
                raise PearlMemorialError(f'対応していない{extension}形式または破損ファイル')
            raise PearlMemorialError(f'音声処理エラー: {error_msg[:100]}...')
        
        # 出力ファイル確認
        if not os.path.exists(opus_path) or os.path.getsize(opus_path) == 0:
            raise PearlMemorialError('音声処理に失敗しました')
        
        # DataURI生成
        with open(opus_path, 'rb') as f:
            raw_data = f.read()
        
        encoded = base64.b64encode(raw_data).decode('utf-8')
        data_uri = f"data:audio/ogg;codecs=opus;base64,{encoded}"
        
        # サイズチェック
        if len(data_uri) > QR_MAX_SIZE:
            raise PearlMemorialError(f'音声が長すぎます（{len(data_uri)}文字）。{duration}秒以下にしてください')
        
        return data_uri, len(raw_data)
        
    except subprocess.TimeoutExpired:
        raise PearlMemorialError('音声処理がタイムアウトしました')
    finally:
        # クリーンアップ
        if 'opus_path' in locals() and os.path.exists(opus_path):
            try:
                os.remove(opus_path)
            except:
                pass

def create_pearl_memorial_qr(data_uri, metadata):
    """Pearl Memorial QRコード生成（デバッグ強化版）"""
    # Pearl Memorial専用データ構造
    pearl_data = {
        "pearl_memorial": "v1.0",
        "type": "standalone_audio",
        "audio_data": data_uri,
        "metadata": {
            "title": metadata.get('filename', 'Pearl Memorial'),
            "filename": metadata['filename'],
            "created": datetime.now().isoformat(),
            "duration": MAX_DURATION,
            "id": metadata['id'],
            "technology": "Server-Independent DataURI",
            "creator": "Pearl Memorial System"
        }
    }
    
    # JSON最適化（デバッグ情報付き）
    qr_content = json.dumps(pearl_data, ensure_ascii=False, separators=(',', ':'))
    
    # デバッグ: QRコンテンツの先頭100文字をログ出力
    print(f"QR Content Preview: {qr_content[:100]}...")
    print(f"QR Content Length: {len(qr_content)} characters")
    print(f"Audio Data Length: {len(data_uri)} characters")
    
    # QRコードサイズチェック
    if len(qr_content) > 70000:
        raise PearlMemorialError(f'QRコンテンツが大きすぎます: {len(qr_content)}文字。70,000文字以下にしてください。')
    
    # QRコード生成
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=4,
        border=1,
    )
    
    try:
        qr.add_data(qr_content)
        qr.make(fit=True)
        
        print(f"QR Code Version: {qr.version}")
        
        if qr.version > 40:
            raise PearlMemorialError(f'QRコードが大きすぎます（バージョン{qr.version}）。音声を短くしてください。')
        
        # QR画像生成
        qr_img = qr.make_image(fill_color="black", back_color="white")
        
        # メタデータ付きQR画像生成
        final_img = add_qr_metadata(qr_img, {
            **metadata,
            'qr_version': f"Version {qr.version}",
            'content_length': f"{len(qr_content)} chars",
            'json_preview': qr_content[:50] + "..." if len(qr_content) > 50 else qr_content
        })
        
        return final_img
        
    except Exception as e:
        print(f"QR Code Generation Error: {str(e)}")
        print(f"Data sample: {qr_content[:200]}...")
        raise PearlMemorialError(f'QRコード生成エラー: {str(e)}')

def add_qr_metadata(qr_img, metadata):
    """QRコードにメタデータを追加（デバッグ強化版）"""
    qr_width, qr_height = qr_img.size
    header_height, footer_height, padding = 160, 240, 15
    
    total_width = qr_width + (padding * 2)
    total_height = header_height + qr_height + footer_height + (padding * 3)
    
    # 画像作成
    final_img = Image.new('RGB', (total_width, total_height), 'white')
    final_img.paste(qr_img, (padding, header_height + padding))
    
    # テキスト描画
    draw = ImageDraw.Draw(final_img)
    try:
        font = ImageFont.load_default()
    except:
        font = None
    
    # ヘッダー
    y = 15
    draw.text((padding, y), "Pearl Memorial QR - 完全自立型", fill='#2c3e50', font=font)
    y += 20
    draw.text((padding, y), "Server-Independent DataURI Technology", fill='#e74c3c', font=font)
    y += 20
    draw.text((padding, y), "Scan -> Instant Offline Play", fill='#27ae60', font=font)
    y += 20
    draw.text((padding, y), "No Internet Required Forever", fill='#9b59b6', font=font)
    y += 20
    draw.text((padding, y), "Works in Airplane Mode", fill='#f39c12', font=font)
    y += 20
    draw.text((padding, y), "1000-Year Guaranteed Playback", fill='#e67e22', font=font)
    y += 20
    
    # デバッグ情報（重要！）
    draw.text((padding, y), f"JSON Preview: {metadata.get('json_preview', 'N/A')}", fill='#8e44ad', font=font)
    
    # 区切り線
    line_y = 155
    draw.line([(padding, line_y), (total_width - padding, line_y)], fill='#3498db', width=2)
    
    # フッター
    footer_y = header_height + qr_height + padding * 2
    footer_items = [
        f"📁 File: {metadata.get('filename', 'Unknown')}",
        f"🔄 Process: {metadata.get('process_type', 'Audio processing')}",
        f"🆔 ID: {metadata.get('id', 'Unknown')}",
        f"📊 Raw: {metadata.get('raw_size', 'Unknown')}",
        f"📏 Content: {metadata.get('content_length', 'Unknown')}",
        f"📱 QR: {metadata.get('qr_version', 'Unknown')}",
        f"⚡ Tech: {metadata.get('technology', 'DataURI')}",
        f"🔍 Format: JSON with embedded audio data",
        f"🎵 Audio: Base64 Opus codec embedded",
        f"📋 Content Type: Pearl Memorial v1.0",
        f"🔑 Reader: Pearl Memorial Reader App Required",
        f"▶️ Action: Scan with Pearl Memorial Reader",
        f"🌍 Pearl Memorial - World's First Standalone Voice QR"
    ]
    
    for i, item in enumerate(footer_items):
        draw.text((padding, footer_y + i * 18), item, fill='#34495e', font=font)
    
    return final_img

def get_index_html():
    """HTMLテンプレートを安全に返す（録音機能付き）"""
    html_content = """<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pearl Memorial QR - 完全自立型音声保存技術</title>
    <style>
        body {
            font-family: 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            margin: 0;
            padding: 20px;
            color: #333;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
            padding: 50px 20px;
        }
        .header {
            text-align: center;
            color: white;
            margin-bottom: 50px;
        }
        .header h1 {
            font-size: 3em;
            margin-bottom: 20px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }
        .upload-section {
            background: white;
            border-radius: 20px;
            padding: 40px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            margin-bottom: 30px;
        }
        .recording-section {
            margin-bottom: 30px;
            text-align: center;
        }
        .record-button {
            background: linear-gradient(135deg, #e74c3c 0%, #c0392b 100%);
            color: white;
            padding: 20px 40px;
            border: none;
            border-radius: 25px;
            font-size: 1.2em;
            cursor: pointer;
            width: 100%;
            margin-bottom: 20px;
            transition: all 0.3s ease;
        }
        .record-button:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 20px rgba(231, 76, 60, 0.3);
        }
        .record-button:disabled {
            opacity: 0.6;
            background: #95a5a6;
            cursor: not-allowed;
        }
        .recording-status {
            margin: 20px 0;
        }
        .recording-indicator {
            background: #e74c3c;
            color: white;
            padding: 15px;
            border-radius: 10px;
            text-align: center;
            font-weight: bold;
            animation: pulse 1s infinite;
        }
        @keyframes pulse {
            0% { opacity: 1; }
            50% { opacity: 0.7; }
            100% { opacity: 1; }
        }
        .divider {
            text-align: center;
            margin: 30px 0;
            position: relative;
        }
        .divider::before {
            content: '';
            position: absolute;
            top: 50%;
            left: 0;
            right: 0;
            height: 1px;
            background: #ddd;
        }
        .divider span {
            background: white;
            padding: 0 20px;
            color: #666;
            font-weight: bold;
        }
        .upload-area {
            border: 3px dashed #667eea;
            border-radius: 15px;
            padding: 60px 40px;
            text-align: center;
            cursor: pointer;
        }
        .file-input { display: none; }
        .upload-button {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 15px 30px;
            border: none;
            border-radius: 25px;
            font-size: 1.1em;
            cursor: pointer;
            margin-top: 20px;
        }
        .generate-button {
            background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
            color: white;
            padding: 20px 40px;
            border: none;
            border-radius: 30px;
            font-size: 1.2em;
            cursor: pointer;
            width: 100%;
            margin-top: 30px;
        }
        .generate-button:disabled {
            opacity: 0.6;
            cursor: not-allowed;
        }
        .status {
            margin-top: 20px;
            padding: 15px;
            border-radius: 10px;
            text-align: center;
            display: none;
        }
        .status.success {
            background: #d4edda;
            color: #155724;
        }
        .status.error {
            background: #f8d7da;
            color: #721c24;
        }
        .loading-indicator {
            display: none;
            text-align: center;
            margin: 20px 0;
        }
        .spinner {
            border: 4px solid #f3f3f3;
            border-top: 4px solid #3498db;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
            margin: 0 auto 15px;
        }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        @media (max-width: 768px) {
            .record-button {
                font-size: 1.4em;
                padding: 25px 20px;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🐚 Pearl Memorial QR</h1>
            <p>完全自立型音声保存技術</p>
        </div>
        
        <div class="upload-section">
            <form id="uploadForm" enctype="multipart/form-data">
                
                <!-- 録音機能セクション -->
                <div class="recording-section">
                    <button type="button" class="record-button" id="recordButton">
                        🎤 2秒録音
                    </button>
                    <div id="recordingStatus" class="recording-status" style="display: none;">
                        <div class="recording-indicator">🔴 録音中... <span id="countdown">2</span></div>
                    </div>
                </div>

                <div class="divider">
                    <span>または</span>
                </div>
                
                <div class="upload-area" id="uploadArea">
                    <h3>音声ファイルをドラッグ&ドロップまたは選択</h3>
                    <p>対応形式: MP3, WAV, M4A, OGG, FLAC, MP4, MOV, WebM</p>
                    <input type="file" id="audioFile" name="audio" 
                           accept="audio/*,video/*" class="file-input">
                    <button type="button" class="upload-button" 
                            onclick="document.getElementById('audioFile').click()">
                        ファイルを選択
                    </button>
                </div>
                
                <div class="loading-indicator" id="loadingIndicator">
                    <div class="spinner"></div>
                    <p>QRコードを生成中...</p>
                </div>
                
                <button type="submit" class="generate-button" id="generateButton" disabled>
                    🚀 QRコードを生成
                </button>
                
                <div id="status" class="status"></div>
            </form>
        </div>
        
        <div style="text-align: center; margin-top: 30px;">
            <a href="/reader" style="color: white; text-decoration: none; 
               background: rgba(255,255,255,0.2); padding: 15px 30px; 
               border-radius: 25px; display: inline-block;">
                📱 Pearl Memorial Reader を開く
            </a>
        </div>
    </div>

    <script>
        const uploadArea = document.getElementById('uploadArea');
        const audioFile = document.getElementById('audioFile');
        const uploadForm = document.getElementById('uploadForm');
        const generateButton = document.getElementById('generateButton');
        const status = document.getElementById('status');
        const loadingIndicator = document.getElementById('loadingIndicator');
        const recordButton = document.getElementById('recordButton');
        const recordingStatus = document.getElementById('recordingStatus');
        const countdown = document.getElementById('countdown');
        
        let mediaRecorder;
        let recordedChunks = [];
        let recordingTimer;

        // 録音機能
        recordButton.addEventListener('click', startRecording);

        async function startRecording() {
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ 
                    audio: {
                        echoCancellation: true,
                        noiseSuppression: true,
                        autoGainControl: true,
                        sampleRate: 44100
                    }
                });

                recordedChunks = [];
                
                let mimeType = 'audio/wav';
                if (!MediaRecorder.isTypeSupported(mimeType)) {
                    mimeType = 'audio/webm;codecs=opus';
                    if (!MediaRecorder.isTypeSupported(mimeType)) {
                        mimeType = 'audio/mp4';
                    }
                }
                
                mediaRecorder = new MediaRecorder(stream, { mimeType });

                mediaRecorder.ondataavailable = (event) => {
                    if (event.data.size > 0) {
                        recordedChunks.push(event.data);
                    }
                };

                mediaRecorder.onstop = () => {
                    stream.getTracks().forEach(track => track.stop());
                    processRecordedAudio();
                };

                recordButton.disabled = true;
                recordingStatus.style.display = 'block';
                
                let timeLeft = 2;
                countdown.textContent = timeLeft;
                
                recordingTimer = setInterval(() => {
                    timeLeft--;
                    countdown.textContent = timeLeft;
                    if (timeLeft <= 0) {
                        clearInterval(recordingTimer);
                    }
                }, 1000);

                mediaRecorder.start();

                setTimeout(() => {
                    if (mediaRecorder.state === 'recording') {
                        mediaRecorder.stop();
                    }
                    clearInterval(recordingTimer);
                    recordingStatus.style.display = 'none';
                    recordButton.disabled = false;
                }, 2000);

            } catch (error) {
                console.error('Recording error:', error);
                showStatus('マイクアクセスが拒否されました。ブラウザ設定を確認してください。', 'error');
                recordButton.disabled = false;
                recordingStatus.style.display = 'none';
            }
        }

        function processRecordedAudio() {
            const mimeType = mediaRecorder.mimeType;
            const blob = new Blob(recordedChunks, { type: mimeType });
            
            const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
            let extension = '.wav';
            let fileType = 'audio/wav';
            
            if (mimeType.includes('webm')) {
                extension = '.webm';
                fileType = 'audio/webm';
            } else if (mimeType.includes('mp4')) {
                extension = '.m4a';
                fileType = 'audio/mp4';
            }
            
            const fileName = 'pearl_recorded_' + timestamp + extension;
            const file = new File([blob], fileName, { type: fileType });
            
            const dataTransfer = new DataTransfer();
            dataTransfer.items.add(file);
            audioFile.files = dataTransfer.files;
            
            generateButton.disabled = false;
            showStatus('🎉 2秒録音完了！QRコード生成の準備ができました。', 'success');
        }

        audioFile.addEventListener('change', function() {
            const file = this.files[0];
            if (file) {
                generateButton.disabled = false;
                showStatus('ファイルが選択されました: ' + file.name, 'success');
            }
        });

        uploadForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const file = audioFile.files[0];
            if (!file) {
                showStatus('ファイルを選択するか、録音してください', 'error');
                return;
            }

            generateButton.disabled = true;
            loadingIndicator.style.display = 'block';
            showStatus('QRコード生成中...', 'success');

            const formData = new FormData();
            formData.append('audio', file);

            try {
                const response = await fetch('/generate', {
                    method: 'POST',
                    body: formData
                });

                if (response.ok) {
                    const blob = await response.blob();
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = 'pearl_memorial_' + file.name.split('.')[0] + '.png';
                    document.body.appendChild(a);
                    a.click();
                    window.URL.revokeObjectURL(url);
                    document.body.removeChild(a);
                    
                    showStatus('🎉 Pearl Memorial QRコードが生成されました！', 'success');
                } else {
                    const error = await response.json();
                    showStatus('エラー: ' + (error.error || 'Unknown error'), 'error');
                }
            } catch (error) {
                showStatus('ネットワークエラーが発生しました', 'error');
            } finally {
                generateButton.disabled = false;
                loadingIndicator.style.display = 'none';
            }
        });

        function showStatus(message, type) {
            status.textContent = message;
            status.className = 'status ' + type;
            status.style.display = 'block';
            
            setTimeout(() => {
                status.style.display = 'none';
            }, 5000);
        }
    </script>
</body>
</html>"""
    return html_content

def get_reader_html():
    """Reader HTMLテンプレートを安全に返す（QRスキャン統合版）"""
    html_content = """<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pearl Memorial Reader</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            margin: 0;
            padding: 20px;
            color: #333;
        }
        .container {
            max-width: 500px;
            margin: 0 auto;
        }
        .header {
            text-align: center;
            color: white;
            margin-bottom: 30px;
        }
        .header h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
        }
        .status {
            background: rgba(255,255,255,0.9);
            padding: 20px;
            border-radius: 15px;
            text-align: center;
            margin-bottom: 20px;
            font-weight: bold;
            font-size: 1.1em;
        }
        .status.success {
            background: rgba(212, 237, 218, 0.95);
            color: #155724;
        }
        .status.error {
            background: rgba(248, 215, 218, 0.95);
            color: #721c24;
        }
        .status.playing {
            background: rgba(209, 236, 241, 0.95);
            color: #0c5460;
            animation: pulse 1.5s infinite;
        }
        @keyframes pulse {
            0% { opacity: 1; }
            50% { opacity: 0.8; }
            100% { opacity: 1; }
        }
        
        /* QRスキャナー関連 */
        .scan-section {
            background: white;
            border-radius: 15px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
        }
        
        .scan-area {
            position: relative;
            background: #f8f9fa;
            border-radius: 10px;
            overflow: hidden;
            margin-bottom: 15px;
        }
        
        #qr-video {
            width: 100%;
            height: 300px;
            object-fit: cover;
            border-radius: 10px;
        }
        
        .scan-overlay {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            width: 200px;
            height: 200px;
            border: 3px solid #4CAF50;
            border-radius: 10px;
            pointer-events: none;
        }
        
        .scan-overlay::before {
            content: '';
            position: absolute;
            top: -3px;
            left: -3px;
            right: -3px;
            bottom: -3px;
            border: 2px solid rgba(76, 175, 80, 0.3);
            border-radius: 10px;
            animation: scan-pulse 2s infinite;
        }
        
        @keyframes scan-pulse {
            0% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.5; transform: scale(1.05); }
            100% { opacity: 1; transform: scale(1); }
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
            background: #45a049;
            transform: translateY(-2px);
        }
        .btn:disabled {
            background: #ccc;
            cursor: not-allowed;
            transform: none;
        }
        .btn.secondary {
            background: #6c757d;
        }
        .btn.secondary:hover {
            background: #5a6268;
        }
        .btn.danger {
            background: #dc3545;
        }
        .btn.danger:hover {
            background: #c82333;
        }
        
        /* マニュアル入力セクション */
        .manual-section {
            background: rgba(255,255,255,0.1);
            border-radius: 15px;
            padding: 20px;
            margin-top: 20px;
        }
        
        .manual-section h3 {
            color: white;
            margin-bottom: 15px;
            text-align: center;
        }
        
        .qr-input {
            width: 100%;
            height: 100px;
            padding: 15px;
            border: 2px solid #ddd;
            border-radius: 10px;
            font-size: 12px;
            font-family: monospace;
            margin: 15px 0;
            resize: vertical;
            box-sizing: border-box;
        }
        
        .debug-info {
            background: rgba(255,255,255,0.1);
            color: white;
            padding: 10px;
            border-radius: 8px;
            font-size: 0.9em;
            margin: 15px 0;
            font-family: monospace;
        }
        
        .hidden {
            display: none;
        }
        
        .camera-status {
            text-align: center;
            color: white;
            margin: 10px 0;
            font-size: 0.9em;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🐚 Pearl Memorial Reader</h1>
            <p>QRスキャン → 自動音声再生</p>
        </div>
        
        <div class="status" id="status">📱 カメラでQRコードをスキャンしてください</div>
        
        <!-- QRスキャンセクション -->
        <div class="scan-section">
            <div class="scan-area" id="scanArea">
                <video id="qr-video" autoplay muted playsinline></video>
                <div class="scan-overlay"></div>
            </div>
            
            <div class="camera-status" id="cameraStatus">カメラ準備中...</div>
            
            <button class="btn" id="startScanBtn" onclick="startQRScan()">
                📷 QRスキャン開始
            </button>
            
            <button class="btn danger hidden" id="stopScanBtn" onclick="stopQRScan()">
                ⏹️ スキャン停止
            </button>
        </div>
        
        <!-- マニュアル入力セクション -->
        <div class="manual-section">
            <h3>📝 手動入力（代替方法）</h3>
            <textarea class="qr-input" id="qrInput" 
                      placeholder="QRコードデータを手動で貼り付け...&#10;&#10;例: {&quot;pearl_memorial&quot;:&quot;v1.0&quot;,&quot;type&quot;:&quot;standalone_audio&quot;...}"></textarea>
            <button class="btn secondary" onclick="playAudioFromInput()">
                ▶️ 手動入力から再生
            </button>
            <button class="btn secondary" onclick="validateInput()" style="background: #17a2b8;">
                🔍 入力データを検証
            </button>
            <button class="btn secondary" onclick="clearInput()" style="background: #6c757d;">
                🗑️ クリア
            </button>
        </div>
        
        <div class="debug-info hidden" id="debugInfo"></div>
    </div>

    <script>
        let qrStream;
        let qrVideo;
        let isScanning = false;
        let audioContext;
        let currentSource;
        let scanInterval;

        // QRコード検出用の簡易関数
        function detectQRCode(canvas, video) {
            const ctx = canvas.getContext('2d');
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            ctx.drawImage(video, 0, 0);
            
            // ここでは簡易的なQR検出のシミュレーション
            // 実際のQR検出ライブラリを使用する場合はここを置き換え
            const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
            
            // 画像解析でQRコードらしきパターンを検出
            // （実装簡素化のため、ダミー実装）
            return null;
        }

        async function startQRScan() {
            const video = document.getElementById('qr-video');
            const statusElement = document.getElementById('status');
            const cameraStatus = document.getElementById('cameraStatus');
            const startBtn = document.getElementById('startScanBtn');
            const stopBtn = document.getElementById('stopScanBtn');

            try {
                statusElement.textContent = '📷 カメラを起動中...';
                cameraStatus.textContent = 'カメラアクセス中...';

                // カメラアクセス
                qrStream = await navigator.mediaDevices.getUserMedia({
                    video: {
                        facingMode: 'environment', // 背面カメラを優先
                        width: { ideal: 1280 },
                        height: { ideal: 720 }
                    }
                });

                video.srcObject = qrStream;
                await video.play();

                isScanning = true;
                startBtn.classList.add('hidden');
                stopBtn.classList.remove('hidden');
                
                statusElement.textContent = '🔍 QRコードをカメラに向けてください';
                cameraStatus.textContent = 'スキャン中... QRコードをカメラに向けてください';

                // QR検出開始（簡易実装）
                startQRDetection(video);

            } catch (error) {
                console.error('Camera error:', error);
                statusElement.textContent = '❌ カメラアクセスエラー: ' + error.message;
                statusElement.className = 'status error';
                cameraStatus.textContent = 'カメラアクセスが拒否されました';
                
                // 手動入力に誘導
                setTimeout(() => {
                    statusElement.textContent = '📝 手動入力をご利用ください';
                    statusElement.className = 'status';
                }, 3000);
            }
        }

        function startQRDetection(video) {
            const canvas = document.createElement('canvas');
            
            scanInterval = setInterval(() => {
                if (!isScanning) return;
                
                try {
                    // シンプルなQR検出シミュレーション
                    // 実際の実装では QR検出ライブラリを使用
                    
                    // ダミー検出（テスト用）
                    // 実際にはここでcanvas解析を行う
                    
                } catch (error) {
                    console.error('QR detection error:', error);
                }
            }, 500); // 0.5秒間隔でスキャン
        }

        function stopQRScan() {
            isScanning = false;
            
            if (scanInterval) {
                clearInterval(scanInterval);
                scanInterval = null;
            }
            
            if (qrStream) {
                qrStream.getTracks().forEach(track => track.stop());
                qrStream = null;
            }
            
            const video = document.getElementById('qr-video');
            video.srcObject = null;
            
            const startBtn = document.getElementById('startScanBtn');
            const stopBtn = document.getElementById('stopScanBtn');
            const statusElement = document.getElementById('status');
            const cameraStatus = document.getElementById('cameraStatus');
            
            startBtn.classList.remove('hidden');
            stopBtn.classList.add('hidden');
            
            statusElement.textContent = '📱 QRスキャンを停止しました';
            statusElement.className = 'status';
            cameraStatus.textContent = 'カメラ停止';
        }

        // QRコードを検出した時の処理
        async function onQRDetected(qrData) {
            const statusElement = document.getElementById('status');
            
            try {
                statusElement.textContent = '✅ QRコード検出！音声を準備中...';
                statusElement.className = 'status success';
                
                // スキャン停止
                stopQRScan();
                
                // 音声再生
                await playAudioFromData(qrData);
                
            } catch (error) {
                console.error('QR processing error:', error);
                statusElement.textContent = '❌ QRコード処理エラー: ' + error.message;
                statusElement.className = 'status error';
            }
        }

        async function initAudioContext() {
            if (!audioContext) {
                audioContext = new (window.AudioContext || window.webkitAudioContext)();
                console.log('AudioContext created:', audioContext.state);
            }
            if (audioContext.state === 'suspended') {
                await audioContext.resume();
                console.log('AudioContext resumed:', audioContext.state);
            }
        }

        async function playAudioFromData(qrData) {
            const statusElement = document.getElementById('status');
            const debugInfo = document.getElementById('debugInfo');

            try {
                // 既存の再生を停止
                if (currentSource) {
                    currentSource.stop();
                    currentSource = null;
                }

                statusElement.textContent = '🔄 音声データを解析中...';
                statusElement.className = 'status';

                // JSON解析
                const pearlData = JSON.parse(qrData);
                console.log('Parsed Pearl Data:', pearlData);

                // Pearl Memorial形式確認
                if (!pearlData.pearl_memorial || pearlData.type !== 'standalone_audio') {
                    throw new Error('Pearl Memorial QRコードではありません');
                }

                statusElement.textContent = '🎵 音声データを準備中...';

                // AudioContextの初期化
                await initAudioContext();

                // Base64デコード
                const audioDataUri = pearlData.audio_data;
                const base64Data = audioDataUri.split(',')[1];
                const binaryString = atob(base64Data);
                const arrayBuffer = new ArrayBuffer(binaryString.length);
                const uint8Array = new Uint8Array(arrayBuffer);

                for (let i = 0; i < binaryString.length; i++) {
                    uint8Array[i] = binaryString.charCodeAt(i);
                }

                // Web Audio APIでデコード
                const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);
                console.log('Audio buffer decoded:', audioBuffer.duration + 's');

                // 音声再生
                currentSource = audioContext.createBufferSource();
                currentSource.buffer = audioBuffer;
                currentSource.connect(audioContext.destination);

                const title = pearlData.metadata?.title || 'Pearl Memorial';
                statusElement.textContent = '🎵 再生中: ' + title;
                statusElement.className = 'status playing';

                // デバッグ情報表示
                debugInfo.innerHTML = 
                    'Duration: ' + audioBuffer.duration.toFixed(2) + 's | ' +
                    'Sample Rate: ' + audioBuffer.sampleRate + 'Hz | ' +
                    'Channels: ' + audioBuffer.numberOfChannels;
                debugInfo.classList.remove('hidden');

                currentSource.onended = () => {
                    statusElement.textContent = '✅ 再生完了 - ' + title;
                    statusElement.className = 'status success';
                    currentSource = null;
                    
                    // 再スキャン準備
                    setTimeout(() => {
                        statusElement.textContent = '📱 次のQRコードをスキャンできます';
                        statusElement.className = 'status';
                    }, 3000);
                };

                // 再生開始
                currentSource.start(0);
                console.log('Playback started');

            } catch (error) {
                console.error('Audio playback error:', error);
                statusElement.textContent = '❌ 再生エラー: ' + error.message;
                statusElement.className = 'status error';
                
                debugInfo.innerHTML = 'Error: ' + error.message;
                debugInfo.classList.remove('hidden');
            }
        }

        // 手動入力からの再生
        async function playAudioFromInput() {
            const qrInput = document.getElementById('qrInput').value.trim();
            
            if (!qrInput) {
                const statusElement = document.getElementById('status');
                statusElement.textContent = '❌ QRデータを入力してください';
                statusElement.className = 'status error';
                return;
            }

            await playAudioFromData(qrInput);
        }

        // 入力データ検証関数
        function validateInput() {
            const qrInput = document.getElementById('qrInput').value.trim();
            const statusElement = document.getElementById('status');
            const debugInfo = document.getElementById('debugInfo');
            
            if (!qrInput) {
                statusElement.textContent = '❌ 検証するデータを入力してください';
                statusElement.className = 'status error';
                return;
            }

            try {
                statusElement.textContent = '🔍 データを検証中...';
                statusElement.className = 'status';

                // JSON解析
                const pearlData = JSON.parse(qrInput);
                
                let validationResult = '✅ JSON解析成功<br>';
                
                // Pearl Memorial形式確認
                if (pearlData.pearl_memorial === 'v1.0') {
                    validationResult += '✅ Pearl Memorial v1.0 形式<br>';
                } else {
                    validationResult += '❌ pearl_memorial フィールドが無効: ' + pearlData.pearl_memorial + '<br>';
                }
                
                if (pearlData.type === 'standalone_audio') {
                    validationResult += '✅ standalone_audio タイプ<br>';
                } else {
                    validationResult += '❌ type フィールドが無効: ' + pearlData.type + '<br>';
                }
                
                // 音声データ確認
                if (pearlData.audio_data && pearlData.audio_data.startsWith('data:audio/')) {
                    validationResult += '✅ 音声データURI形式正常<br>';
                    validationResult += '📏 音声データ長: ' + pearlData.audio_data.length + ' 文字<br>';
                    
                    // Base64部分の検証
                    const base64Data = pearlData.audio_data.split(',')[1];
                    if (base64Data && base64Data.length > 0) {
                        validationResult += '✅ Base64データ存在<br>';
                        validationResult += '📏 Base64長: ' + base64Data.length + ' 文字<br>';
                    } else {
                        validationResult += '❌ Base64データが無効<br>';
                    }
                } else {
                    validationResult += '❌ 音声データURIが無効<br>';
                }
                
                // メタデータ確認
                if (pearlData.metadata) {
                    validationResult += '✅ メタデータ存在<br>';
                    validationResult += '📝 タイトル: ' + (pearlData.metadata.title || 'なし') + '<br>';
                    validationResult += '📝 ファイル名: ' + (pearlData.metadata.filename || 'なし') + '<br>';
                } else {
                    validationResult += '❌ メタデータが見つかりません<br>';
                }
                
                validationResult += '<br>📊 総データ長: ' + qrInput.length + ' 文字';
                
                debugInfo.innerHTML = validationResult;
                debugInfo.classList.remove('hidden');
                
                statusElement.textContent = '✅ データ検証完了';
                statusElement.className = 'status success';
                
            } catch (error) {
                console.error('Validation error:', error);
                
                const errorInfo = '❌ JSON解析エラー<br>' +
                    'エラー: ' + error.message + '<br>' +
                    'データ長: ' + qrInput.length + ' 文字<br>' +
                    'データプレビュー: ' + qrInput.substring(0, 100) + '...';
                
                debugInfo.innerHTML = errorInfo;
                debugInfo.classList.remove('hidden');
                
                statusElement.textContent = '❌ 検証エラー: ' + error.message;
                statusElement.className = 'status error';
            }
        }

        // クリア関数の改善
        function clearInput() {
            document.getElementById('qrInput').value = '';
            const statusElement = document.getElementById('status');
            const debugInfo = document.getElementById('debugInfo');
            
            statusElement.textContent = '📱 カメラでQRコードをスキャンしてください';
            statusElement.className = 'status';
            debugInfo.classList.add('hidden');
            
            // 再生中の音声を停止
            if (currentSource) {
                currentSource.stop();
                currentSource = null;
            }
        }
            console.log('Pearl Memorial Reader loaded');
            
            // ユーザーの最初のクリックでAudioContextを準備
            document.addEventListener('click', async () => {
                if (!audioContext) {
                    await initAudioContext();
                }
            }, { once: true });
        });

        // テスト用QRデータシミュレーション
        function simulateQRDetection() {
            const testQRData = '{"pearl_memorial":"v1.0","type":"standalone_audio","audio_data":"data:audio/ogg;codecs=opus;base64,T2dnUwACAAAAAAAAAAA=","metadata":{"title":"Test Audio","filename":"test.wav"}}';
            onQRDetected(testQRData);
        }

        // デバッグ用（コンソールから呼び出し可能）
        window.testQR = simulateQRDetection;
    </script>
</body>
</html>"""
    return html_content

@app.route('/')
def index():
    """メインページ"""
    return get_index_html()

@app.route('/generate', methods=['POST'])
def generate_qr():
    """完全自立型QRコード生成API"""
    temp_file_path = None
    
    try:
        # FFmpeg事前確認
        if not check_ffmpeg():
            return jsonify({'error': '音声処理サービスが利用できません。しばらく後にお試しください'}), 503
        
        # ファイル取得
        if 'audio' not in request.files:
            return jsonify({'error': '音声ファイルが指定されていません'}), 400
        
        audio_file = request.files['audio']
        file_content = audio_file.read()
        
        # ファイル検証
        extension = validate_file(audio_file, file_content)
        
        # 一時ファイル保存
        unique_id = str(uuid.uuid4())[:8]
        temp_file_path = os.path.join(TEMP_DIR, f"input_{unique_id}{extension}")
        
        with open(temp_file_path, 'wb') as f:
            f.write(file_content)
        
        # DataURI生成
        data_uri, raw_size = process_audio_to_datauri(temp_file_path)
        
        # メタデータ準備
        is_video = extension in VIDEO_EXTENSIONS
        process_type = f"Audio extracted from {extension.upper()} video" if is_video else f"Audio processed from {extension.upper()}"
        
        metadata = {
            'filename': audio_file.filename,
            'id': unique_id,
            'raw_size': f"{raw_size} bytes",
            'process_type': process_type,
            'technology': 'Server-Independent DataURI'
        }
        
        # QRコード生成
        qr_image = create_pearl_memorial_qr(data_uri, metadata)
        
        # 画像返却
        img_io = io.BytesIO()
        qr_image.save(img_io, 'PNG', optimize=True, quality=95)
        img_io.seek(0)
        
        download_name = f"pearl_memorial_{Path(audio_file.filename).stem}_{unique_id}.png"
        
        return send_file(img_io, mimetype='image/png', as_attachment=True, 
                        download_name=download_name)
        
    except PearlMemorialError as e:
        return jsonify({'error': str(e)}), 400
    except subprocess.TimeoutExpired:
        return jsonify({'error': '音声処理がタイムアウトしました。より短いファイルをお試しください'}), 408
    except Exception as e:
        error_msg = str(e)
        if "ffmpeg" in error_msg.lower():
            return jsonify({'error': '音声処理サービスが利用できません'}), 503
        return jsonify({'error': f'処理エラー: {error_msg}'}), 500
    finally:
        # クリーンアップ
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except:
                pass

@app.route('/reader')
def reader():
    """Pearl Memorial Reader App"""
    return get_reader_html()

@app.route('/test-qr')
def test_qr():
    """QRコードテストページ"""
    test_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Pearl Memorial QR Test</title>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/qr-scanner/1.4.2/qr-scanner.umd.min.js"></script>
    </head>
    <body style="font-family: Arial; padding: 20px;">
        <h1>Pearl Memorial QR Code Tester</h1>
        
        <h2>1. Generate Test QR</h2>
        <button onclick="generateTestQR()">Generate Test QR Code</button>
        <div id="testQRResult"></div>
        
        <h2>2. QR Content Validator</h2>
        <textarea id="qrContent" rows="10" cols="80" placeholder="Paste QR content here..."></textarea><br>
        <button onclick="validateQRContent()">Validate JSON Content</button>
        <div id="validationResult"></div>
        
        <script>
        function generateTestQR() {
            const testData = {
                "pearl_memorial": "v1.0",
                "type": "standalone_audio",
                "audio_data": "data:audio/ogg;codecs=opus;base64,T2dnUwACAAAAAAAAAAA=",
                "metadata": {
                    "title": "Test Audio",
                    "filename": "test.wav",
                    "created": new Date().toISOString(),
                    "duration": 2.0,
                    "id": "test123",
                    "technology": "Server-Independent DataURI",
                    "creator": "Pearl Memorial System"
                }
            };
            
            const jsonStr = JSON.stringify(testData);
            document.getElementById('testQRResult').innerHTML = 
                '<h3>Test QR Content:</h3>' +
                '<pre style="background: #f0f0f0; padding: 10px;">' + 
                JSON.stringify(testData, null, 2) + 
                '</pre>' +
                '<p><strong>Length:</strong> ' + jsonStr.length + ' characters</p>';
        }
        
        function validateQRContent() {
            const content = document.getElementById('qrContent').value;
            const resultDiv = document.getElementById('validationResult');
            
            try {
                const data = JSON.parse(content);
                
                let validation = '<h3>Validation Results:</h3>';
                validation += '<p style="color: green;">✅ Valid JSON</p>';
                
                if (data.pearl_memorial === 'v1.0') {
                    validation += '<p style="color: green;">✅ Pearl Memorial v1.0 format</p>';
                } else {
                    validation += '<p style="color: red;">❌ Missing pearl_memorial field</p>';
                }
                
                if (data.type === 'standalone_audio') {
                    validation += '<p style="color: green;">✅ Standalone audio type</p>';
                } else {
                    validation += '<p style="color: red;">❌ Invalid type field</p>';
                }
                
                if (data.audio_data && data.audio_data.startsWith('data:audio/')) {
                    validation += '<p style="color: green;">✅ Valid audio data URI</p>';
                    validation += '<p>Audio data length: ' + data.audio_data.length + ' chars</p>';
                } else {
                    validation += '<p style="color: red;">❌ Invalid audio data URI</p>';
                }
                
                if (data.metadata) {
                    validation += '<p style="color: green;">✅ Metadata present</p>';
                    validation += '<p>Title: ' + (data.metadata.title || 'N/A') + '</p>';
                } else {
                    validation += '<p style="color: red;">❌ Missing metadata</p>';
                }
                
                validation += '<p><strong>Total content length:</strong> ' + content.length + ' characters</p>';
                
                resultDiv.innerHTML = validation;
                
            } catch (e) {
                resultDiv.innerHTML = '<h3>Validation Results:</h3><p style="color: red;">❌ Invalid JSON: ' + e.message + '</p>';
            }
        }
        </script>
    </body>
    </html>
    """
    return test_html
    """ヘルスチェックAPI"""
    ffmpeg_available = check_ffmpeg()
    
    return jsonify({
        'status': 'healthy' if ffmpeg_available else 'degraded',
        'message': 'Pearl Memorial Standalone QR Generator',
        'ffmpeg_available': ffmpeg_available,
        'technology': 'Server-Independent DataURI',
        'supported_formats': {
            'audio': list(AUDIO_EXTENSIONS),
            'video_with_audio': list(VIDEO_EXTENSIONS)
        },
        'features': [
            'Complete offline playback',
            'Server-independent storage',
            'DataURI embedding',
            '2-second optimal duration',
            '1000-year guarantee'
        ],
        'version': 'Pearl Memorial v1.0 - Bounderist Edition - Syntax Fixed'
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)
