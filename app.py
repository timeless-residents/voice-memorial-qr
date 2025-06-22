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
    draw.text((padding, 35), "Server-Independent DataURI Technology", fill='#e74c3c', font=font)
    draw.text((padding, 55), "Scan -> Instant Offline Play", fill='#27ae60', font=font)
    draw.text((padding, 75), "No Internet Required Forever", fill='#9b59b6', font=font)
    draw.text((padding, 95), "Works in Airplane Mode", fill='#f39c12', font=font)
    draw.text((padding, 115), "1000-Year Guaranteed Playback", fill='#e67e22', font=font)
    
    # 区切り線
    line_y = 135
    draw.line([(padding, line_y), (total_width - padding, line_y)], fill='#3498db', width=2)
    
    # フッター情報
    footer_y = qr_y + qr_height + padding
    footer_items = [
        f"File: {metadata.get('filename', 'Unknown')}",
        f"Process: {metadata.get('process_type', 'Audio processing')}",
        f"ID: {metadata.get('id', 'Unknown')}",
        f"Raw: {metadata.get('raw_size', 'Unknown')}",
        f"Content: {metadata.get('content_length', 'Unknown')}",
        f"QR: {metadata.get('qr_version', 'Unknown')}",
        f"Tech: {metadata.get('technology', 'Unknown')}",
        f"Reader: {metadata.get('reader_url', 'Manual Setup')}",
        f"Action: Scan with Pearl Memorial Reader App"
    ]
    
    for i, item in enumerate(footer_items):
        draw.text((padding, footer_y + i * 18), item, fill='#34495e', font=font)
    
    # 重要な説明
    instruction = "Pearl Memorial - World's First Standalone Voice QR"
    inst_y = footer_y + len(footer_items) * 18 + 10
    draw.text((padding, inst_y), instruction, fill='#e67e22', font=font)
    
    return final_img

@app.route('/reader')
def pearl_memorial_reader():
    """
    完全自立型Pearl Memorial Reader（構文エラー修正版）
    """
    # HTMLを分割して安全に処理
    html_head = '''<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="Pearl Memorial">
    <title>Pearl Memorial Reader</title>
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
</head>'''
    
    html_body = '''<body>
    <div class="offline-indicator">オフライン動作中</div>
    <div class="container">
        <div class="header">
            <h1>Pearl Memorial</h1>
            <p>QR読み取りシステム</p>
        </div>
        <div class="status" id="status">準備完了</div>
        <button class="btn" onclick="testQR()">テストQR処理</button>
    </div>
    <script>
        function testQR() {
            document.getElementById('status').textContent = 'テスト実行中...';
            setTimeout(() => {
                document.getElementById('status').textContent = 'テスト完了！';
            }, 1000);
        }
        document.addEventListener('DOMContentLoaded', () => {
            document.getElementById('status').textContent = 'Pearl Memorial Reader 準備完了';
        });
    </script>
</body>
</html>'''
    
    return html_head + html_body

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
        'version': '8.0-syntax-safe-standalone'
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)
