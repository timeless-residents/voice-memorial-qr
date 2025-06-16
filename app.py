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

app = Flask(__name__)

TEMP_DIR = tempfile.gettempdir()

def check_ffmpeg():
    """ffmpeg利用可能性確認"""
    try:
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except:
        return False

def process_audio_for_hybrid_qr(audio_file_path, output_duration=2.5):
    """
    音声→RAWデータ→URL埋め込み用処理（subprocess直接実行版）
    """
    if not check_ffmpeg():
        raise Exception("FFmpeg not available on this system")
    
    try:
        unique_id = str(uuid.uuid4())[:8]
        
        # ffmpeg処理（subprocess直接実行）
        opus_path = os.path.join(TEMP_DIR, f"processed_{unique_id}.opus")
        
        # ffmpegコマンド構築
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
            raise Exception(f"FFmpeg processing failed: {result.stderr}")
        
        # 出力ファイル確認
        if not os.path.exists(opus_path) or os.path.getsize(opus_path) == 0:
            raise Exception("FFmpeg produced empty output file")
        
        # RAWデータ読み込み
        with open(opus_path, 'rb') as f:
            raw_opus_data = f.read()
        
        # base64エンコード
        encoded_data = base64.b64encode(raw_opus_data).decode('utf-8')
        
        # URL長制限チェック（Safari対応）
        if len(encoded_data) > 70000:
            raise Exception(f"Audio too long for URL embedding: {len(encoded_data)} chars")
        
        # クリーンアップ
        if os.path.exists(opus_path):
            os.remove(opus_path)
        
        return encoded_data, len(raw_opus_data)
        
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
def generate_hybrid_qr():
    """
    ハイブリッドQRコード生成（subprocess直接実行版）
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
        
        # ファイルサイズ制限
        file_content = audio_file.read()
        if len(file_content) > 5 * 1024 * 1024:
            return jsonify({'error': 'File too large. Max 5MB for optimal processing.'}), 400
        
        # ファイル形式確認
        allowed_extensions = {'.mp3', '.m4a', '.wav', '.aac', '.ogg', '.flac'}
        file_extension = Path(audio_file.filename).suffix.lower()
        if file_extension not in allowed_extensions:
            return jsonify({'error': f'Unsupported file format. Supported: {", ".join(allowed_extensions)}'}), 400
        
        # 一時ファイル保存
        unique_id = str(uuid.uuid4())[:8]
        audio_file_path = os.path.join(TEMP_DIR, f"input_{unique_id}{file_extension}")
        
        with open(audio_file_path, 'wb') as f:
            f.write(file_content)
        
        # ファイル保存確認
        if not os.path.exists(audio_file_path) or os.path.getsize(audio_file_path) == 0:
            raise Exception("Failed to save uploaded file")
        
        # RAWデータ処理
        encoded_raw_data, raw_size = process_audio_for_hybrid_qr(audio_file_path)
        
        # URLセーフエンコード
        url_safe_data = urllib.parse.quote(encoded_raw_data, safe='')
        
        # ハイブリッドURL生成
        base_url = request.url_root.rstrip('/')
        hybrid_url = f"{base_url}/play?data={url_safe_data}&filename={urllib.parse.quote(audio_file.filename)}&id={unique_id}"
        
        # URL長最終確認
        if len(hybrid_url) > 80000:
            return jsonify({'error': f'Generated URL too long: {len(hybrid_url)} chars. Try shorter audio.'}), 400
        
        # QRコード生成
        qr = qrcode.QRCode(
            version=None,  # 自動サイズ調整
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=4,
            border=1,
        )
        
        qr.add_data(hybrid_url)
        qr.make(fit=True)
        
        # QRコード画像生成
        qr_img = qr.make_image(fill_color="black", back_color="white")
        
        # メタデータ付きQRコード
        final_img = create_hybrid_qr(qr_img, {
            'title': 'Voice Memorial QR',
            'filename': audio_file.filename,
            'raw_size': f"{raw_size} bytes",
            'url_length': f"{len(hybrid_url)} chars",
            'technology': 'URL + RAW Data Hybrid',
            'id': unique_id
        })
        
        # 画像返却
        img_io = io.BytesIO()
        final_img.save(img_io, 'PNG', optimize=True, quality=95)
        img_io.seek(0)
        
        return send_file(
            img_io,
            mimetype='image/png',
            as_attachment=True,
            download_name=f"voice_qr_{Path(audio_file.filename).stem}_{unique_id}.png"
        )
        
    except subprocess.CalledProcessError as e:
        return jsonify({'error': f'Audio processing failed: {str(e)}'}), 500
    except Exception as e:
        error_msg = str(e)
        if "timeout" in error_msg.lower():
            return jsonify({'error': 'Audio processing timeout. Try a shorter file.'}), 408
        elif "ffmpeg" in error_msg.lower():
            return jsonify({'error': 'Audio processing service unavailable. Please try again later.'}), 503
        else:
            return jsonify({'error': f'Processing failed: {error_msg}'}), 500
    finally:
        # 確実なクリーンアップ
        if audio_file_path and os.path.exists(audio_file_path):
            try:
                os.remove(audio_file_path)
            except:
                pass

@app.route('/play')
def play_hybrid():
    """
    URLパラメータからRAWデータ直接復元・再生（subprocess直接実行版）
    """
    opus_path = None
    m4a_path = None
    
    try:
        # FFmpeg利用可能性確認
        if not check_ffmpeg():
            return create_error_page("Audio playback service temporarily unavailable", 503)
        
        encoded_data = request.args.get('data')
        filename = request.args.get('filename', 'voice_memorial.m4a')
        audio_id = request.args.get('id', 'unknown')
        
        if not encoded_data:
            return create_error_page("No audio data in URL", 400)
        
        # URLデコード → base64デコード → RAW音声復元
        try:
            url_decoded_data = urllib.parse.unquote(encoded_data)
            raw_opus_data = base64.b64decode(url_decoded_data)
        except Exception as e:
            return create_error_page("Invalid audio data format", 400)
        
        if len(raw_opus_data) == 0:
            return create_error_page("Empty audio data", 400)
        
        # 一時ファイル作成
        unique_id = str(uuid.uuid4())[:8]
        opus_path = os.path.join(TEMP_DIR, f"decoded_{unique_id}.opus")
        m4a_path = os.path.join(TEMP_DIR, f"decoded_{unique_id}.m4a")
        
        # RAWデータ → opusファイル
        with open(opus_path, 'wb') as f:
            f.write(raw_opus_data)
        
        # ファイル作成確認
        if not os.path.exists(opus_path) or os.path.getsize(opus_path) == 0:
            return create_error_page("Failed to create temporary audio file", 500)
        
        # opus → m4a変換（再生用）
        ffmpeg_cmd = [
            'ffmpeg',
            '-i', opus_path,
            '-c:a', 'aac',
            '-b:a', '128k',
            '-ar', '44100',
            '-y',
            m4a_path
        ]
        
        result = subprocess.run(
            ffmpeg_cmd, 
            capture_output=True, 
            text=True,
            timeout=30,
            check=False
        )
        
        if result.returncode != 0:
            return create_error_page(f"Audio conversion failed: {result.stderr}", 500)
        
        # 変換結果確認
        if not os.path.exists(m4a_path) or os.path.getsize(m4a_path) == 0:
            return create_error_page("Audio conversion produced empty file", 500)
        
        # 音声ファイル返却
        return send_file(
            m4a_path,
            mimetype='audio/mp4',
            as_attachment=False,  # ブラウザで直接再生
            download_name=f"voice_memorial_{Path(filename).stem}.m4a"
        )
        
    except subprocess.TimeoutExpired:
        return create_error_page("Audio processing timeout", 408)
    except Exception as e:
        return create_error_page(f"Playback failed: {str(e)}", 500)
    finally:
        # 確実なクリーンアップ
        for path in [opus_path, m4a_path]:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except:
                    pass

def create_error_page(error_message, status_code):
    """エラーページ生成"""
    return f"""
    <html>
    <head>
        <title>Voice Memorial QR - エラー</title>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{ font-family: Arial, sans-serif; padding: 50px; text-align: center; background: #f8f9fa; }}
            .container {{ max-width: 600px; margin: 0 auto; background: white; padding: 40px; border-radius: 15px; box-shadow: 0 10px 30px rgba(0,0,0,0.1); }}
            .error {{ color: #e74c3c; font-size: 1.5em; margin: 20px 0; }}
            .back-link {{ background: #3498db; color: white; padding: 15px 30px; border-radius: 25px; text-decoration: none; display: inline-block; margin-top: 20px; }}
            .status {{ color: #666; font-size: 0.9em; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🚫 Voice Memorial QR</h1>
            <div class="error">{error_message}</div>
            <div class="status">Status Code: {status_code}</div>
            <a href="/" class="back-link">新しい音声QRコードを作成</a>
            <p style="margin-top: 30px; color: #666; font-size: 0.9em;">
                サーバーが起動中の場合、少々お待ちください。<br>
                世界初のハイブリッド音声QR技術のデモンストレーション中です。
            </p>
        </div>
    </body>
    </html>
    """, status_code

def create_hybrid_qr(qr_img, metadata):
    """
    ブランド化QRコード生成（完全版）
    """
    qr_width, qr_height = qr_img.size
    header_height, footer_height, padding = 100, 140, 15
    
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
    title = metadata.get('title', 'Voice Memorial QR')
    draw.text((padding, 15), title, fill='#2c3e50', font=font)
    
    # 技術的特徴強調
    draw.text((padding, 35), "URL + RAW Data Hybrid Technology", fill='#e74c3c', font=font)
    draw.text((padding, 55), "Scan → Instant Play & Download", fill='#27ae60', font=font)
    draw.text((padding, 75), "Server-Independent Permanence", fill='#8e44ad', font=font)
    
    # 区切り線
    line_y = 95
    draw.line([(padding, line_y), (total_width - padding, line_y)], fill='#3498db', width=2)
    
    # フッター情報
    footer_y = qr_y + qr_height + padding
    footer_items = [
        f"File: {metadata.get('filename', 'Unknown')}",
        f"ID: {metadata.get('id', 'Unknown')}",
        f"Raw: {metadata.get('raw_size', 'Unknown')}",
        f"URL: {metadata.get('url_length', 'Unknown')}",
        f"Tech: {metadata.get('technology', 'Unknown')}",
        f"Action: Scan for instant playback"
    ]
    
    for i, item in enumerate(footer_items):
        draw.text((padding, footer_y + i * 18), item, fill='#34495e', font=font)
    
    # 重要な説明
    instruction = "🎵 World's First Hybrid Voice QR Technology"
    inst_y = footer_y + len(footer_items) * 18 + 10
    draw.text((padding, inst_y), instruction, fill='#e67e22', font=font)
    
    return final_img

@app.route('/health')
def health_check():
    """ヘルスチェック（FFmpeg対応版）"""
    ffmpeg_available = check_ffmpeg()
    
    return jsonify({
        'status': 'healthy' if ffmpeg_available else 'degraded',
        'message': 'Voice Memorial Hybrid QR Service',
        'ffmpeg_available': ffmpeg_available,
        'technology': 'URL + RAW Data Embedding (subprocess direct)',
        'features': [
            'Audio processing (ffmpeg direct)',
            'Hybrid QR generation',
            'URL-based instant playback',
            'Server-independent permanence',
            'Cold start optimization'
        ],
        'limitations': {
            'free_tier': 'Cold start delay possible',
            'max_audio_duration': '3 seconds optimal',
            'max_file_size': '5MB'
        },
        'version': '5.0-production-subprocess-direct'
    })

@app.route('/status')
def service_status():
    """詳細サービス状態"""
    try:
        # システム状態確認
        temp_space = shutil.disk_usage(TEMP_DIR)
        free_space_gb = temp_space.free / (1024**3)
        
        ffmpeg_version = None
        if check_ffmpeg():
            try:
                result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    ffmpeg_version = result.stdout.split('\n')[0]
            except:
                pass
        
        return jsonify({
            'service': 'Voice Memorial QR',
            'status': 'operational',
            'ffmpeg': {
                'available': check_ffmpeg(),
                'version': ffmpeg_version
            },
            'system': {
                'temp_space_gb': round(free_space_gb, 2),
                'temp_directory': TEMP_DIR
            },
            'endpoints': {
                '/': 'Main interface',
                '/generate': 'QR generation',
                '/play': 'Audio playback',
                '/health': 'Health check',
                '/status': 'Detailed status'
            }
        })
    except Exception as e:
        return jsonify({
            'service': 'Voice Memorial QR',
            'status': 'error',
            'error': str(e)
        }), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)
