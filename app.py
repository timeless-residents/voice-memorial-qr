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
    
    # 区切り線
    line_y = 135
    draw.line([(padding, line_y), (total_width - padding, line_y)], fill='#3498db', width=2)
    
    # フッター
    footer_y = header_height + qr_height + padding * 2
    footer_items = [
        f"File: {metadata.get('filename', 'Unknown')}",
        f"Process: {metadata.get('process_type', 'Audio processing')}",
        f"ID: {metadata.get('id', 'Unknown')}",
        f"Raw: {metadata.get('raw_size', 'Unknown')}",
        f"Content: {metadata.get('content_length', 'Unknown')}",
        f"QR: {metadata.get('qr_version', 'Unknown')}",
        f"Tech: {metadata.get('technology', 'DataURI')}",
        f"Reader: Pearl Memorial Reader App Required",
        f"Action: Scan with Pearl Memorial Reader",
        f"Pearl Memorial - World's First Standalone Voice QR"
    ]
    
    for i, item in enumerate(footer_items):
        draw.text((padding, footer_y + i * 18), item, fill='#34495e', font=font)
    
    return final_img

def get_index_html():
    """HTMLテンプレートを安全に返す"""
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
                showStatus('ファイルを選択してください', 'error');
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
                    
                    showStatus('QRコードが生成されました！', 'success');
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
    """Reader HTMLテンプレートを安全に返す"""
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
        }
        .qr-input {
            width: 100%;
            height: 120px;
            padding: 15px;
            border: 2px solid #ddd;
            border-radius: 10px;
            font-size: 14px;
            margin: 15px 0;
            resize: vertical;
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
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🐚 Pearl Memorial Reader</h1>
            <p>完全オフライン音声再生</p>
        </div>
        
        <div class="status" id="status">QRコードデータを貼り付けてください</div>
        
        <textarea class="qr-input" id="qrInput" 
                  placeholder="Pearl Memorial QRコードのデータをここに貼り付け..."></textarea>
        
        <button class="btn" onclick="playAudioFromQR()">▶️ 音声を再生</button>
        <button class="btn" onclick="clearInput()" style="background: #95a5a6;">🗑️ クリア</button>
    </div>

    <script>
        let audioContext;

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
                statusElement.textContent = 'QRデータを入力してください';
                return;
            }

            try {
                await initAudioContext();
                statusElement.textContent = '音声データを解析中...';

                const pearlData = JSON.parse(qrInput);
                
                if (!pearlData.pearl_memorial || pearlData.type !== 'standalone_audio') {
                    throw new Error('Pearl Memorial QRコードではありません');
                }

                const audioDataUri = pearlData.audio_data;
                const base64Data = audioDataUri.split(',')[1];
                const binaryString = atob(base64Data);
                const arrayBuffer = new ArrayBuffer(binaryString.length);
                const uint8Array = new Uint8Array(arrayBuffer);

                for (let i = 0; i < binaryString.length; i++) {
                    uint8Array[i] = binaryString.charCodeAt(i);
                }

                const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);
                const source = audioContext.createBufferSource();
                source.buffer = audioBuffer;
                source.connect(audioContext.destination);

                const title = pearlData.metadata?.title || 'Pearl Memorial';
                statusElement.textContent = '再生中: ' + title;

                source.onended = () => {
                    statusElement.textContent = '再生完了';
                };

                source.start(0);

            } catch (error) {
                statusElement.textContent = 'エラー: ' + error.message;
            }
        }

        function clearInput() {
            document.getElementById('qrInput').value = '';
            document.getElementById('status').textContent = 'QRコードデータを貼り付けてください';
        }
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
        'version': 'Pearl Memorial v1.0 - Bounderist Edition - Syntax Fixed'
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)
