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

app = Flask(__name__)

TEMP_DIR = tempfile.gettempdir()

def process_audio_for_hybrid_qr(audio_file_path, output_duration=3):
    """
    音声→RAWデータ→URL埋め込み用処理
    """
    try:
        unique_id = str(uuid.uuid4())[:8]
        
        # ffmpeg処理（実証済み技術）
        opus_path = os.path.join(TEMP_DIR, f"processed_{unique_id}.opus")
        
        ffmpeg_cmd = [
            'ffmpeg', '-i', audio_file_path,
            '-af', 'highpass=f=80,lowpass=f=8000',
            '-c:a', 'libopus',
            '-b:a', '1k',
            '-ar', '8000',
            '-t', str(output_duration),
            '-y',
            opus_path
        ]
        
        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise Exception(f"FFmpeg processing failed: {result.stderr}")
        
        # RAWデータ読み込み
        with open(opus_path, 'rb') as f:
            raw_opus_data = f.read()
        
        # base64エンコード
        encoded_data = base64.b64encode(raw_opus_data).decode('utf-8')
        
        # URL長制限チェック（Safari対応）
        if len(encoded_data) > 70000:
            raise Exception(f"Audio too long for URL embedding: {len(encoded_data)} chars")
        
        # クリーンアップ
        os.remove(opus_path)
        
        return encoded_data, len(raw_opus_data)
        
    except Exception as e:
        if 'opus_path' in locals() and os.path.exists(opus_path):
            os.remove(opus_path)
        raise e

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate', methods=['POST'])
def generate_hybrid_qr():
    """
    ハイブリッドQRコード生成
    """
    audio_file_path = None
    try:
        if 'audio' not in request.files:
            return jsonify({'error': 'No audio file provided'}), 400
        
        audio_file = request.files['audio']
        if audio_file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        # ファイルサイズ制限
        file_content = audio_file.read()
        if len(file_content) > 5 * 1024 * 1024:
            return jsonify({'error': 'File too large. Max 5MB.'}), 400
        
        # 一時ファイル保存
        unique_id = str(uuid.uuid4())[:8]
        file_extension = Path(audio_file.filename).suffix or '.m4a'
        audio_file_path = os.path.join(TEMP_DIR, f"input_{unique_id}{file_extension}")
        
        with open(audio_file_path, 'wb') as f:
            f.write(file_content)
        
        # RAWデータ処理
        encoded_raw_data, raw_size = process_audio_for_hybrid_qr(audio_file_path)
        
        # URLセーフエンコード
        url_safe_data = urllib.parse.quote(encoded_raw_data, safe='')
        
        # ハイブリッドURL生成
        base_url = request.url_root.rstrip('/')
        hybrid_url = f"{base_url}/play?data={url_safe_data}&filename={urllib.parse.quote(audio_file.filename)}&id={unique_id}"
        
        # URL長最終確認
        if len(hybrid_url) > 80000:
            return jsonify({'error': f'Generated URL too long: {len(hybrid_url)} chars'}), 400
        
        # QRコード生成
        qr = qrcode.QRCode(
            version=None,
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
            'technology': 'URL + RAW Data Hybrid'
        })
        
        # 画像返却
        img_io = io.BytesIO()
        final_img.save(img_io, 'PNG', optimize=True)
        img_io.seek(0)
        
        return send_file(
            img_io,
            mimetype='image/png',
            as_attachment=True,
            download_name=f"voice_qr_{Path(audio_file.filename).stem}_{unique_id}.png"
        )
        
    except Exception as e:
        return jsonify({'error': f'Generation failed: {str(e)}'}), 500
    finally:
        if audio_file_path and os.path.exists(audio_file_path):
            os.remove(audio_file_path)

@app.route('/play')
def play_hybrid():
    """
    URLパラメータからRAWデータ直接復元・再生
    """
    try:
        encoded_data = request.args.get('data')
        filename = request.args.get('filename', 'voice_memorial.m4a')
        audio_id = request.args.get('id', 'unknown')
        
        if not encoded_data:
            return jsonify({'error': 'No audio data in URL'}), 400
        
        # URLデコード → base64デコード → RAW音声復元
        url_decoded_data = urllib.parse.unquote(encoded_data)
        raw_opus_data = base64.b64decode(url_decoded_data)
        
        # 一時ファイル作成
        unique_id = str(uuid.uuid4())[:8]
        opus_path = os.path.join(TEMP_DIR, f"decoded_{unique_id}.opus")
        m4a_path = os.path.join(TEMP_DIR, f"decoded_{unique_id}.m4a")
        
        # RAWデータ → opusファイル
        with open(opus_path, 'wb') as f:
            f.write(raw_opus_data)
        
        # opus → m4a変換（再生用）
        ffmpeg_cmd = [
            'ffmpeg', '-i', opus_path,
            '-c:a', 'aac', '-b:a', '128k', '-ar', '44100',
            '-y', m4a_path
        ]
        
        result = subprocess.run(ffmpeg_cmd, capture_output=True)
        if result.returncode != 0:
            raise Exception("Audio conversion failed")
        
        # 音声ファイル返却
        return send_file(
            m4a_path,
            mimetype='audio/mp4',
            as_attachment=False,
            download_name=f"voice_memorial_{Path(filename).stem}.m4a"
        )
        
    except Exception as e:
        return f"""
        <html><body style="font-family: Arial; padding: 50px; text-align: center;">
            <h1>🚫 音声再生エラー</h1>
            <p>エラー: {str(e)}</p>
            <p><a href="/">新しい音声QRコードを作成</a></p>
        </body></html>
        """, 500
    finally:
        for path_var in ['opus_path', 'm4a_path']:
            if path_var in locals():
                path = locals()[path_var]
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except:
                        pass

def create_hybrid_qr(qr_img, metadata):
    """
    ブランド化QRコード生成
    """
    qr_width, qr_height = qr_img.size
    header_height, footer_height, padding = 100, 120, 15
    
    total_width = qr_width + (padding * 2)
    total_height = header_height + qr_height + footer_height + (padding * 3)
    
    final_img = Image.new('RGB', (total_width, total_height), 'white')
    final_img.paste(qr_img, (padding, header_height + padding))
    
    draw = ImageDraw.Draw(final_img)
    try:
        font = ImageFont.load_default()
    except:
        font = None
    
    # ヘッダー
    draw.text((padding, 15), metadata.get('title', 'Voice Memorial QR'), fill='#2c3e50', font=font)
    draw.text((padding, 35), "⚡ URL + RAW Data Hybrid", fill='#e74c3c', font=font)
    draw.text((padding, 55), "📱 Scan → Instant Play", fill='#27ae60', font=font)
    
    # 区切り線
    draw.line([(padding, 80), (total_width - padding, 80)], fill='#3498db', width=2)
    
    # フッター
    footer_y = header_height + qr_height + padding * 2
    footer_items = [
        f"📁 {metadata.get('filename', 'Unknown')}",
        f"💾 {metadata.get('raw_size', 'Unknown')}",
        f"🔗 URL: {metadata.get('url_length', 'Unknown')}",
        f"🛡️ Tech: {metadata.get('technology', 'Unknown')}"
    ]
    
    for i, item in enumerate(footer_items):
        draw.text((padding, footer_y + i * 18), item, fill='#34495e', font=font)
    
    return final_img

@app.route('/health')
def health_check():
    return jsonify({
        'status': 'healthy',
        'message': 'Voice Memorial Hybrid QR Service',
        'technology': 'URL + RAW Data Embedding',
        'version': '4.0-production-ready'
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)
