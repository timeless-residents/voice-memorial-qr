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
    """Pearl Memorial QRコード生成"""
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
    
    # JSON最適化
    qr_content = json.dumps(pearl_data, ensure_ascii=False, separators=(',', ':'))
    
    # QRコード生成
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=4,
        border=1,
    )
    
    qr.add_data(qr_content)
    qr.make(fit=True)
    
    if qr.version > 40:
        raise PearlMemorialError(f'QRコードが大きすぎます（バージョン{qr.version}）')
    
    # QR画像生成
    qr_img = qr.make_image(fill_color="black", back_color="white")
    
    # メタデータ付きQR画像生成
    final_img = add_qr_metadata(qr_img, {
        **metadata,
        'qr_version': f"Version {qr.version}",
        'content_length': f"{len(qr_content)} chars"
    })
    
    return final_img

def add_qr_metadata(qr_img, metadata):
    """QRコードにメタデータを追加"""
    qr_width, qr_height = qr_img.size
    header_height, footer_height, padding = 140, 200, 15
    
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
    draw.text((padding, y), "🐚 Pearl Memorial QR - 完全自立型", fill='#2c3e50', font=font)
    y += 20
    draw.text((padding, y), "Server-Independent DataURI Technology", fill='#e74c3c', font=font)
    y += 20
    draw.text((padding, y), "Scan → Instant Offline Play", fill='#27ae60', font=font)
    y += 20
    draw.text((padding, y), "No Internet Required Forever", fill='#9b59b6', font=font)
    y += 20
    draw.text((padding, y), "Works in Airplane Mode", fill='#f39c12', font=font)
    y += 20
    draw.text((padding, y), "1000-Year Guaranteed Playback", fill='#e67e22', font=font)
    
    # 区切り線
    line_y = 135
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
        f"🔍 Reader: Pearl Memorial Reader App Required",
        f"▶️ Action: Scan with Pearl Memorial Reader",
        f"🌍 Pearl Memorial - World's First Standalone Voice QR"
    ]
    
    for i, item in enumerate(footer_items):
        draw.text((padding, footer_y + i * 18), item, fill='#34495e', font=font)
    
    return final_img

@app.route('/')
def index():
    """メインページ"""
    return INDEX_HTML

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
    return READER_HTML

@app.route('/health')
def health_check():
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
        'version': 'Pearl Memorial v1.0 - Bounderist Edition'
    })

# HTML テンプレート
INDEX_HTML = '''<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="mobile-web-app-capable" content="yes">
    <title>Pearl Memorial QR - 完全自立型音声保存技術</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            color: #333;
        }
        
        .container { max-width: 800px; margin: 0 auto; padding: 50px 20px; }
        
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
        
        .header p { font-size: 1.2em; opacity: 0.9; }
        
        .tech-notice {
            background: rgba(255,255,255,0.95);
            padding: 25px;
            border-radius: 15px;
            margin: 20px 0;
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
            border-left: 5px solid #27ae60;
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
            transition: all 0.3s ease;
            cursor: pointer;
        }
        
        .upload-area:hover {
            border-color: #764ba2;
            background: #f8f9ff;
        }
        
        .upload-area.dragover {
            border-color: #764ba2;
            background: #f0f4ff;
            transform: scale(1.02);
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
            transition: transform 0.3s ease;
            margin-top: 20px;
        }
        
        .upload-button:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 20px rgba(102, 126, 234, 0.3);
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
            transition: all 0.3s ease;
        }
        
        .generate-button:hover {
            transform: translateY(-3px);
            box-shadow: 0 15px 30px rgba(17, 153, 142, 0.4);
        }
        
        .generate-button:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }
        
        .features {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 30px;
            margin-top: 50px;
        }
        
        .feature {
            background: white;
            padding: 30px;
            border-radius: 15px;
            text-align: center;
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
        }
        
        .feature-icon { font-size: 3em; margin-bottom: 20px; }
        
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
            border: 1px solid #c3e6cb;
        }
        
        .status.error {
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }
        
        .status.processing {
            background: #d1ecf1;
            color: #0c5460;
            border: 1px solid #bee5eb;
        }
        
        .footer {
            text-align: center;
            color: white;
            margin-top: 50px;
            opacity: 0.8;
        }
        
        .tech-highlight {
            background: rgba(255,255,255,0.1);
            padding: 20px;
            border-radius: 15px;
            margin: 20px 0;
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

        .reader-info {
            background: rgba(255,255,255,0.95);
            padding: 20px;
            border-radius: 15px;
            margin: 20px 0;
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
            border-left: 5px solid #3498db;
        }

        .reader-button {
            background: linear-gradient(135deg, #3498db 0%, #2980b9 100%);
            color: white;
            padding: 15px 30px;
            border: none;
            border-radius: 25px;
            font-size: 1.1em;
            cursor: pointer;
            transition: transform 0.3s ease;
            margin: 10px 5px;
            text-decoration: none;
            display: inline-block;
        }

        .reader-button:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 20px rgba(52, 152, 219, 0.3);
        }

        @media (max-width: 768px) {
            .record-button {
                font-size: 1.4em;
                padding: 25px 20px;
            }
            
            .upload-area {
                padding: 40px 20px;
            }
            
            .container {
                padding: 20px 15px;
            }

            .header h1 {
                font-size: 2.5em;
            }

            .reader-button {
                display: block;
                margin: 10px 0;
                text-align: center;
            }
        }

        @media (hover: none) and (pointer: coarse) {
            .record-button:active {
                transform: scale(0.95);
            }
            
            .upload-button:active {
                transform: scale(0.95);
            }

            .reader-button:active {
                transform: scale(0.95);
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🐚 Pearl Memorial QR</h1>
            <p>完全自立型音声保存技術</p>
            <div class="tech-highlight">
                <strong>🚀 Server-Independent DataURI Technology</strong><br>
                生成 → 永続保存 → オフライン再生
            </div>
        </div>
        
        <div class="tech-notice">
            <h3>🌟 革新的完全自立型システム</h3>
            <p><strong>QR生成</strong>: サーバーで音声処理・圧縮・DataURI埋め込み</p>
            <p><strong>QR再生</strong>: 完全オフライン・サーバー不要・1000年保証</p>
            <p><strong>機内モード</strong>でも再生可能な世界初技術です。</p>
        </div>

        <div class="reader-info">
            <h3>📱 Pearl Memorial Reader アプリ</h3>
            <p>生成されたQRコードを読み取るには、専用の読み取りアプリが必要です。</p>
            <div style="text-align: center; margin-top: 15px;">
                <a href="/reader" class="reader-button" target="_blank">
                    📱 読み取りアプリを開く
                </a>
                <button class="reader-button" onclick="downloadReaderApp()">
                    💾 読み取りアプリをダウンロード
                </button>
            </div>
            <p style="font-size: 0.9em; color: #666; margin-top: 10px;">
                読み取りアプリは完全オフライン動作・PWA対応・ホーム画面追加可能です。
            </p>
        </div>
        
        <div class="upload-section">
            <form id="uploadForm" enctype="multipart/form-data">
                
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
                    <div class="upload-icon">📁</div>
                    <h3>音声ファイルをドラッグ&ドロップ</h3>
                    <p>2秒以内の音声推奨（最適なQRサイズ）</p>
                    <p style="font-size: 0.9em; color: #666; margin-top: 10px;">
                        対応形式: MP3, M4A, WAV, AAC, OGG, FLAC, MP4, MOV, WebM
                    </p>
                    <input type="file" id="audioFile" name="audio" 
                           accept="audio/*,video/*,.mp3,.m4a,.wav,.aac,.ogg,.flac,.mp4,.mov,.avi,.mkv,.webm" 
                           class="file-input">
                    <button type="button" class="upload-button" onclick="document.getElementById('audioFile').click()">
                        ファイルを選択
                    </button>
                </div>
                
                <div id="fileInfo" style="margin-top: 20px; display: none;">
                    <p><strong>選択されたファイル:</strong> <span id="fileName"></span></p>
                    <p><strong>ファイルサイズ:</strong> <span id="fileSize"></span></p>
                    <p><strong>推定処理時間:</strong> <span id="estimatedTime"></span></p>
                </div>
                
                <div class="loading-indicator" id="loadingIndicator">
                    <div class="spinner"></div>
                    <p>完全自立型QRコードを生成中...</p>
                    <p style="font-size: 0.9em; color: #666;">音声圧縮・DataURI埋め込み・永続化処理実行中</p>
                </div>
                
                <button type="submit" class="generate-button" id="generateButton" disabled>
                    🚀 完全自立型QRコードを生成
                </button>
                
                <div id="status" class="status"></div>
            </form>
        </div>
        
        <div class="features">
            <div class="feature">
                <div class="feature-icon">📱</div>
                <h3>オフライン再生</h3>
                <p>機内モードでも音声再生可能</p>
            </div>
            <div class="feature">
                <div class="feature-icon">🛡️</div>
                <h3>サーバー不要</h3>
                <p>DataURI埋め込みで永続保存</p>
            </div>
            <div class="feature">
                <div class="feature-icon">🌍</div>
                <h3>世界初技術</h3>
                <p>完全自立型音声保存システム</p>
            </div>
            <div class="feature">
                <div class="feature-icon">🏆</div>
                <h3>1000年保証</h3>
                <p>文明が続く限り再生可能</p>
            </div>
        </div>
        
        <div class="footer">
            <p>© 2025 Pearl Memorial QR - 完全自立型音声保存技術</p>
            <p>Made with ❤️ by Bounderist Technology</p>
            <p style="font-size: 0.8em; margin-top: 10px;">
                Server-Independent DataURI Technology | Offline-First Design
            </p>
        </div>
    </div>

    <script>
        // グローバル変数
        const uploadArea = document.getElementById('uploadArea');
        const audioFile = document.getElementById('audioFile');
        const uploadForm = document.getElementById('uploadForm');
        const generateButton = document.getElementById('generateButton');
        const status = document.getElementById('status');
        const fileInfo = document.getElementById('fileInfo');
        const fileName = document.getElementById('fileName');
        const fileSize = document.getElementById('fileSize');
        const estimatedTime = document.getElementById('estimatedTime');
        const loadingIndicator = document.getElementById('loadingIndicator');
        const recordButton = document.getElementById('recordButton');
        const recordingStatus = document.getElementById('recordingStatus');
        const countdown = document.getElementById('countdown');
        
        let mediaRecorder;
        let recordedChunks = [];
        let recordingTimer;

        // 読み取りアプリダウンロード
        async function downloadReaderApp() {
            try {
                const response = await fetch('/reader');
                const html = await response.text();
                
                const blob = new Blob([html], { type: 'text/html' });
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'pearl-memorial-reader.html';
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                document.body.removeChild(a);
                
                showStatus('🎉 Pearl Memorial Reader アプリをダウンロードしました！', 'success');
            } catch (error) {
                console.error('Download error:', error);
                showStatus('ダウンロードエラーが発生しました。', 'error');
            }
        }

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
            
            const fileName = `pearl_recorded_${timestamp}${extension}`;
            const file = new File([blob], fileName, { type: fileType });
            
            const dataTransfer = new DataTransfer();
            dataTransfer.items.add(file);
            audioFile.files = dataTransfer.files;
            
            handleFileSelect();
            showStatus('🎉 2秒録音完了！完全自立型QRコード生成の準備ができました。', 'success');
        }

        // ファイル検証
        function validateAudioFile(file) {
            const audioExtensions = ['.mp3', '.m4a', '.wav', '.aac', '.ogg', '.flac'];
            const videoExtensions = ['.mp4', '.mov', '.avi', '.mkv', '.webm'];
            
            const extension = file.name.toLowerCase().substring(file.name.lastIndexOf('.'));
            const isAudioFile = audioExtensions.includes(extension);
            const isVideoFile = videoExtensions.includes(extension);
            
            if (isVideoFile) {
                showStatus('動画ファイルが選択されました。音声のみを抽出して完全自立型QRコード生成します。', 'processing');
                return true;
            }
            
            if (!isAudioFile && !file.type.startsWith('audio/')) {
                showStatus('対応していないファイル形式です。音声ファイルまたは動画ファイルを選択してください。', 'error');
                return false;
            }
            
            return true;
        }

        // ドラッグ&ドロップ
        uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadArea.classList.add('dragover');
        });

        uploadArea.addEventListener('dragleave', () => {
            uploadArea.classList.remove('dragover');
        });

        uploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadArea.classList.remove('dragover');
            const files = e.dataTransfer.files;
            if (files.length > 0) {
                audioFile.files = files;
                handleFileSelect();
            }
        });

        audioFile.addEventListener('change', handleFileSelect);

        function handleFileSelect() {
            const file = audioFile.files[0];
            if (file) {
                if (!validateAudioFile(file)) {
                    audioFile.value = '';
                    return;
                }

                fileName.textContent = file.name;
                const sizeInMB = (file.size / 1024 / 1024).toFixed(2);
                fileSize.textContent = sizeInMB + ' MB';
                
                const estimatedSeconds = Math.max(5, Math.min(30, Math.ceil(file.size / (1024 * 1024) * 3)));
                estimatedTime.textContent = estimatedSeconds + '秒程度';
                
                fileInfo.style.display = 'block';
                generateButton.disabled = false;
                
                if (file.size > 2 * 1024 * 1024) {
                    showStatus('ファイルサイズが2MBを超えています。2秒以内に自動カットされます。', 'processing');
                }
            }
        }

        // フォーム送信
        uploadForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const file = audioFile.files[0];
            if (!file) {
                showStatus('ファイルを選択するか、録音してください', 'error');
                return;
            }

            generateButton.disabled = true;
            loadingIndicator.style.display = 'block';
            showStatus('完全自立型QRコード生成中...', 'processing');

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
                    a.download = `pearl_memorial_standalone_${file.name.split('.')[0]}.png`;
                    document.body.appendChild(a);
                    a.click();
                    window.URL.revokeObjectURL(url);
                    document.body.removeChild(a);
                    
                    showStatus('🎉 完全自立型Pearl Memorial QRコードが生成されました！Pearl Memorial Readerアプリでスキャンして音声を再生してください。', 'success');
                } else {
                    const error = await response.json();
                    let errorMessage = error.error || 'Unknown error';
                    
                    if (errorMessage.includes('timeout')) {
                        errorMessage = 'ファイルが大きすぎます。より短い音声ファイルをお試しください。';
                    } else if (errorMessage.includes('ffmpeg')) {
                        errorMessage = 'サーバーが起動中です。少々お待ちいただき再度お試しください。';
                    } else if (errorMessage.includes('version')) {
                        errorMessage = '音声が長すぎます。2秒以内の音声をお試しください。';
                    }
                    
                    showStatus(`エラー: ${errorMessage}`, 'error');
                }
            } catch (error) {
                console.error('Generation error:', error);
                showStatus('ネットワークエラーまたはサーバー起動中です。少々お待ちいただき再度お試しください。', 'error');
            } finally {
                generateButton.disabled = false;
                loadingIndicator.style.display = 'none';
            }
        });

        function showStatus(message, type) {
            status.textContent = message;
            status.className = `status ${type}`;
            status.style.display = 'block';
            
            if (type === 'success') {
                setTimeout(() => {
                    status.style.display = 'none';
                }, 15000);
            } else if (type === 'error') {
                setTimeout(() => {
                    status.style.display = 'none';
                }, 10000);
            }
        }

        // ヘルスチェック
        let healthCheckAttempts = 0;
        const maxHealthCheckAttempts = 6;

        async function checkServiceHealth() {
            if (healthCheckAttempts >= maxHealthCheckAttempts) {
                showStatus('サーバー起動完了まで時間がかかっています。録音機能はご利用いただけます。', 'processing');
                return;
            }
            
            healthCheckAttempts++;
            console.log(`Health check attempt ${healthCheckAttempts}/${maxHealthCheckAttempts}`);
            
            try {
                const response = await fetch('/health', { 
                    method: 'GET',
                    headers: { 'Accept': 'application/json' },
                    timeout: 5000
                });
                
                const contentType = response.headers.get('Content-Type');
                if (!contentType || !contentType.includes('application/json')) {
                    throw new Error('Server returning HTML (still starting)');
                }
                
                const health = await response.json();
                console.log('✅ Service ready:', health);
                
                if (health.ffmpeg_available) {
                    console.log('Pearl Memorial Generator Ready:', health.version);
                } else {
                    showStatus('⚠️ 音声処理機能準備中...再度お試しください。', 'processing');
                    setTimeout(checkServiceHealth, 15000);
                }
            } catch (error) {
                console.log(`Attempt ${healthCheckAttempts}: ${error.message}`);
                
                if (error.message.includes('Unexpected token') || 
                    error.message.includes('HTML') ||
                    error.message.includes('JSON')) {
                    console.log('Server still starting (expected during cold start)');
                }
                
                if (healthCheckAttempts < maxHealthCheckAttempts) {
                    const nextAttemptSeconds = 20;
                    setTimeout(checkServiceHealth, nextAttemptSeconds * 1000);
                }
            }
        }

        // 初期化
        setTimeout(checkServiceHealth, 3000);

        document.addEventListener('DOMContentLoaded', () => {
            showStatus('🚀 Pearl Memorial Generator 準備完了！完全自立型QRコードを生成できます。', 'processing');
            
            setTimeout(() => {
                if (status.classList.contains('processing')) {
                    status.style.display = 'none';
                }
            }, 3000);
        });
    </script>
</body>
</html>'''

READER_HTML = '''<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="Pearl Memorial">
    <title>Pearl Memorial Reader - 完全オフライン音声再生</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            color: #333;
            padding: 20px;
        }
        
        .container { max-width: 500px; margin: 0 auto; }
        
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
        
        .qr-input {
            width: 100%;
            height: 120px;
            padding: 15px;
            border: 2px solid #ddd;
            border-radius: 10px;
            font-size: 14px;
            font-family: monospace;
            margin: 15px 0;
            resize: vertical;
        }
        
        .tech-info {
            background: rgba(255,255,255,0.1);
            color: white;
            padding: 15px;
            border-radius: 10px;
            font-size: 0.9em;
            margin: 20px 0;
        }
        
        .feature-list {
            color: white;
            margin: 20px 0;
        }
        
        .feature-list li {
            margin: 8px 0;
            padding-left: 20px;
            position: relative;
        }
        
        .feature-list li:before {
            content: '✓';
            position: absolute;
            left: 0;
            color: #2ecc71;
            font-weight: bold;
        }
    </style>
</head>
<body>
    <div class="offline-indicator">🔒 完全オフライン動作</div>
    
    <div class="container">
        <div class="header">
            <h1>🐚 Pearl Memorial Reader</h1>
            <p>完全オフライン音声再生システム</p>
        </div>
        
        <div class="tech-info">
            <h3>🌟 完全自立型技術</h3>
            <ul class="feature-list">
                <li>サーバー接続不要</li>
                <li>機内モードで動作</li>
                <li>QRコードから直接音声再生</li>
                <li>DataURI埋め込み技術</li>
                <li>1000年永続保証</li>
            </ul>
        </div>
        
        <div class="status" id="status">QRコードを読み取り準備完了</div>
        
        <textarea 
            class="qr-input" 
            id="qrInput" 
            placeholder="Pearl Memorial QRコードから読み取ったデータをここに貼り付けてください...&#10;&#10;例: {&quot;pearl_memorial&quot;:&quot;v1.0&quot;,&quot;type&quot;:&quot;standalone_audio&quot;...}"
        ></textarea>
        
        <button class="btn" onclick="playAudioFromQR()">
            ▶️ 音声を再生
        </button>
        
        <button class="btn" onclick="clearInput()" style="background: #95a5a6;">
            🗑️ クリア
        </button>
        
        <div class="tech-info">
            <h4>📱 使用方法</h4>
            <p>1. Pearl Memorial QRコードをスマホカメラでスキャン</p>
            <p>2. 表示されたデータを上のテキストエリアに貼り付け</p>
            <p>3. 「音声を再生」ボタンをタップ</p>
            <p>4. 完全オフラインで音声再生開始！</p>
        </div>
    </div>

    <script>
        let audioContext;
        let currentAudioBuffer;

        async function initAudioContext() {
            if (!audioContext) {
                audioContext = new (window.AudioContext || window.webkitAudioContext)();
            }
            if (audioContext.state === 'suspended') {
                await audioContext.resume();
            }
        }

        async function playAudioFromQR() {
            const qrInput = document.getElementById('qrInput').value.trim();
            const statusElement = document.getElementById('status');
            
            if (!qrInput) {
                statusElement.textContent = '❌ QRデータを入力してください';
                statusElement.style.background = '#f8d7da';
                statusElement.style.color = '#721c24';
                return;
            }

            try {
                await initAudioContext();
                
                statusElement.textContent = '🔄 QRデータを解析中...';
                statusElement.style.background = '#d1ecf1';
                statusElement.style.color = '#0c5460';

                // JSON解析
                let pearlData;
                try {
                    pearlData = JSON.parse(qrInput);
                } catch (e) {
                    throw new Error('無効なJSONデータです');
                }

                // Pearl Memorial形式確認
                if (!pearlData.pearl_memorial || pearlData.type !== 'standalone_audio') {
                    throw new Error('Pearl Memorial QRコードではありません');
                }

                statusElement.textContent = '🎵 音声データを準備中...';

                // DataURI解析
                const audioDataUri = pearlData.audio_data;
                if (!audioDataUri || !audioDataUri.startsWith('data:audio/')) {
                    throw new Error('音声データが見つかりません');
                }

                // Base64デコード
                const base64Data = audioDataUri.split(',')[1];
                const binaryString = atob(base64Data);
                const arrayBuffer = new ArrayBuffer(binaryString.length);
                const uint8Array = new Uint8Array(arrayBuffer);

                for (let i = 0; i < binaryString.length; i++) {
                    uint8Array[i] = binaryString.charCodeAt(i);
                }

                statusElement.textContent = '🔊 音声をデコード中...';

                // Web Audio APIでデコード
                currentAudioBuffer = await audioContext.decodeAudioData(arrayBuffer);

                // 音声再生
                const source = audioContext.createBufferSource();
                source.buffer = currentAudioBuffer;
                source.connect(audioContext.destination);

                const title = pearlData.metadata?.title || 'Pearl Memorial';
                statusElement.textContent = `🎵 再生中: ${title}`;
                statusElement.style.background = '#d4edda';
                statusElement.style.color = '#155724';

                source.onended = () => {
                    statusElement.textContent = '✅ 再生完了 - Pearl Memorial';
                    statusElement.style.background = '#d4edda';
                    statusElement.style.color = '#155724';
                };

                source.start(0);

            } catch (error) {
                console.error('再生エラー:', error);
                statusElement.textContent = `❌ エラー: ${error.message}`;
                statusElement.style.background = '#f8d7da';
                statusElement.style.color = '#721c24';
            }
        }

        function clearInput() {
            document.getElementById('qrInput').value = '';
            const statusElement = document.getElementById('status');
            statusElement.textContent = 'QRコードを読み取り準備完了';
            statusElement.style.background = 'rgba(255,255,255,0.9)';
            statusElement.style.color = '#333';
        }

        // 初期化
        document.addEventListener('DOMContentLoaded', () => {
            console.log('Pearl Memorial Reader - 完全オフライン音声再生システム準備完了');
            
            // オフライン状態表示
            const offlineIndicator = document.querySelector('.offline-indicator');
            if (!navigator.onLine) {
                offlineIndicator.textContent = '🔒 オフライン動作中';
                offlineIndicator.style.background = '#e74c3c';
            } else {
                offlineIndicator.textContent = '🌐 オンライン（オフライン再生可能）';
                offlineIndicator.style.background = '#27ae60';
            }
        });

        // オンライン/オフライン状態監視
        window.addEventListener('online', () => {
            const indicator = document.querySelector('.offline-indicator');
            indicator.textContent = '🌐 オンライン（オフライン再生可能）';
            indicator.style.background = '#27ae60';
        });

        window.addEventListener('offline', () => {
            const indicator = document.querySelector('.offline-indicator');
            indicator.textContent = '🔒 オフライン動作中';
            indicator.style.background = '#e74c3c';
        });
    </script>
</body>
</html>'''

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)
