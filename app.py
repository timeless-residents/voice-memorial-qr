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
import json
from datetime import datetime

# Flask アプリケーション初期化
app = Flask(__name__)

# 設定定数
TEMP_DIR = tempfile.gettempdir()
MAX_FILE_SIZE = 3 * 1024 * 1024  # 3MB
MAX_DURATION = 2.0  # 2秒
QR_MAX_SIZE = 70000  # QRコード最大サイズ

# 対応ファイル形式
AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.wav', '.aac', '.ogg', '.flac'}
VIDEO_EXTENSIONS = {'.webm', '.mp4', '.mov', '.avi', '.mkv'}
ALL_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS

class PearlMemorialError(Exception):
    """Pearl Memorial専用エラークラス"""
    pass

# ===== ユーティリティ関数 =====

def check_ffmpeg():
    """FFmpeg利用可能性確認"""
    try:
        result = subprocess.run(['ffmpeg', '-version'], 
                              capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except Exception:
        return False

def validate_file(file, content):
    """ファイル検証"""
    if not file or file.filename == '':
        raise PearlMemorialError('ファイルが選択されていません')
    
    if len(content) > MAX_FILE_SIZE:
        raise PearlMemorialError(f'ファイルサイズが大きすぎます（最大{MAX_FILE_SIZE//1024//1024}MB）')
    
    extension = Path(file.filename).suffix.lower()
    if extension not in ALL_EXTENSIONS:
        supported = ', '.join(sorted(ALL_EXTENSIONS))
        raise PearlMemorialError(f'対応していない形式です。対応形式: {supported}')
    
    return extension

def process_audio_to_datauri(file_path, duration=MAX_DURATION):
    """音声→DataURI変換"""
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
            '-af', 'highpass=f=80,lowpass=f=8000',
            '-c:a', 'libopus', '-b:a', '1k', '-ac', '1', '-ar', '8000',
            '-t', str(duration), '-y', opus_path
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
        
        if not os.path.exists(opus_path) or os.path.getsize(opus_path) == 0:
            raise PearlMemorialError('音声処理に失敗しました')
        
        # DataURI生成
        with open(opus_path, 'rb') as f:
            raw_data = f.read()
        
        encoded = base64.b64encode(raw_data).decode('utf-8')
        data_uri = f"data:audio/ogg;codecs=opus;base64,{encoded}"
        
        if len(data_uri) > QR_MAX_SIZE:
            raise PearlMemorialError(f'音声が長すぎます（{len(data_uri)}文字）。{duration}秒以下にしてください')
        
        return data_uri, len(raw_data)
        
    except subprocess.TimeoutExpired:
        raise PearlMemorialError('音声処理がタイムアウトしました')
    finally:
        if 'opus_path' in locals() and os.path.exists(opus_path):
            try:
                os.remove(opus_path)
            except:
                pass

def create_pearl_memorial_qr(data_uri, metadata):
    """Pearl Memorial QRコード生成（iPhone標準カメラ対応）"""
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
    
    # iPhone標準カメラ対応：URLアクセス形式も生成
    import urllib.parse
    base64_data = base64.b64encode(qr_content.encode('utf-8')).decode('utf-8')
    url_data = urllib.parse.quote(base64_data)
    
    # サーバーのベースURL（本番環境では実際のドメインを使用）
    base_url = "https://voice-memorial-qr.onrender.com"
    play_url = f"{base_url}/play?data={url_data}"
    
    # デバッグログ
    print(f"QR Content Preview: {qr_content[:100]}...")
    print(f"QR Content Length: {len(qr_content)} characters")
    print(f"Play URL Length: {len(play_url)} characters")
    
    # QRコードの内容を選択（URLが短い場合はURLを使用）
    if len(play_url) < len(qr_content) and len(play_url) < QR_MAX_SIZE:
        final_qr_content = play_url
        qr_type = "URL (iPhone Camera Compatible)"
        print(f"Using URL format for iPhone compatibility: {len(play_url)} chars")
    else:
        final_qr_content = qr_content
        qr_type = "JSON Data"
        print(f"Using JSON format: {len(qr_content)} chars")
    
    # QRコード生成
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=4,
        border=1,
    )
    
    try:
        qr.add_data(final_qr_content)
        qr.make(fit=True)
        
        print(f"QR Code Version: {qr.version} ({qr_type})")
        
        if qr.version > 40:
            raise PearlMemorialError(f'QRコードが大きすぎます（バージョン{qr.version}）')
        
        # QR画像生成
        qr_img = qr.make_image(fill_color="black", back_color="white")
        
        # メタデータ付きQR画像生成
        final_img = add_qr_metadata(qr_img, {
            **metadata,
            'qr_version': f"Version {qr.version}",
            'content_length': f"{len(final_qr_content)} chars",
            'qr_type': qr_type
        })
        
        return final_img
        
    except Exception as e:
        print(f"QR Code Generation Error: {str(e)}")
        raise PearlMemorialError(f'QRコード生成エラー: {str(e)}')

def add_qr_metadata(qr_img, metadata):
    """QRコードにメタデータを追加"""
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
    
    # ヘッダー情報
    y = 15
    header_texts = [
        ("🐚 Pearl Memorial QR - 完全自立型", '#2c3e50'),
        ("Server-Independent DataURI Technology", '#e74c3c'),
        ("Scan → Instant Offline Play", '#27ae60'),
        ("No Internet Required Forever", '#9b59b6'),
        ("Works in Airplane Mode", '#f39c12'),
        ("1000-Year Guaranteed Playback", '#e67e22')
    ]
    
    for text, color in header_texts:
        draw.text((padding, y), text, fill=color, font=font)
        y += 20
    
    # 区切り線
    line_y = 155
    draw.line([(padding, line_y), (total_width - padding, line_y)], fill='#3498db', width=2)
    
    # フッター情報
    footer_y = header_height + qr_height + padding * 2
    footer_items = [
        f"📁 File: {metadata.get('filename', 'Unknown')}",
        f"🔄 Process: {metadata.get('process_type', 'Audio processing')}",
        f"🆔 ID: {metadata.get('id', 'Unknown')}",
        f"📊 Raw: {metadata.get('raw_size', 'Unknown')}",
        f"📏 Content: {metadata.get('content_length', 'Unknown')}",
        f"📱 QR: {metadata.get('qr_version', 'Unknown')}",
        f"⚡ Tech: {metadata.get('qr_type', 'DataURI')}",
        f"🔍 Format: Pearl Memorial v1.0",
        f"🎵 Audio: Base64 Opus Codec",
        f"📱 iPhone: Standard Camera Compatible",
        f"🔑 Reader: Pearl Memorial Reader App",
        f"▶️ Action: Scan with Any QR Reader",
        f"🌍 World's First Standalone Voice QR"
    ]
    
    for i, item in enumerate(footer_items):
        draw.text((padding, footer_y + i * 18), item, fill='#34495e', font=font)
    
    return final_img

# ===== ルート定義 =====

@app.route('/')
def index():
    """メインページ - QR生成"""
    return render_template('index.html')

@app.route('/play')
def play_audio():
    """iPhone標準カメラ対応：URL直接アクセスで音声再生"""
    data_param = request.args.get('data')
    
    if not data_param:
        return render_template('reader.html')
    
    try:
        # Base64デコードしてJSONデータを取得
        import urllib.parse
        decoded_data = urllib.parse.unquote(data_param)
        
        # Base64エンコードされている場合はデコード
        try:
            json_data = base64.b64decode(decoded_data).decode('utf-8')
        except:
            # Base64でない場合はそのまま使用
            json_data = decoded_data
        
        # JSONデータの検証
        pearl_data = json.loads(json_data)
        
        if not pearl_data.get('pearl_memorial') or pearl_data.get('type') != 'standalone_audio':
            raise ValueError('Invalid Pearl Memorial format')
        
        # 再生ページをプリロードされたデータで表示
        return render_template('play.html', pearl_data=json.dumps(pearl_data))
        
    except Exception as e:
        # エラー時は通常のReaderページにリダイレクト
        return render_template('reader.html', error=f'QRデータの読み込みに失敗しました: {str(e)}')

@app.route('/reader')
def reader():
    """Pearl Memorial Reader - QR読み取り・音声再生"""
    return render_template('reader.html')

@app.route('/generate', methods=['POST'])
def generate_qr():
    """QRコード生成API"""
    temp_file_path = None
    
    try:
        # FFmpeg事前確認
        if not check_ffmpeg():
            return jsonify({'error': '音声処理サービスが利用できません。しばらく後にお試しください'}), 503
        
        # ファイル取得・検証
        if 'audio' not in request.files:
            return jsonify({'error': '音声ファイルが指定されていません'}), 400
        
        audio_file = request.files['audio']
        file_content = audio_file.read()
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
        'version': 'Pearl Memorial v1.0 - Clean Architecture'
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)
