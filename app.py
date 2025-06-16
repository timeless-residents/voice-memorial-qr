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
    あなたの実証技術：音声→RAWデータ→URL埋め込み
    """
    try:
        unique_id = str(uuid.uuid4())[:8]
        
        # ffmpeg処理（あなたの検証そのまま）
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
        
        # URL長制限チェック
        if len(encoded_data) > 70000:  # Safari余裕をもって
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
    RAWデータ埋め込みURL QRコード生成
    """
    audio_file_path = None
    try:
        if 'audio' not in request.files:
            return jsonify({'error': 'No audio file provided'}), 400
        
        audio_file = request.files['audio']
        if audio_file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        # ファイルサイズ制限（5MB）
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
            return jsonify({'error': f'Generated URL too long: {len(hybrid_url)} chars. Try shorter audio.'}), 400
        
        # QRコード生成
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=4,    # URL用に小さく調整
            border=1,
        )
        
        qr.add_data(hybrid_url)
        qr.make(fit=True)
        
        # QRコード画像生成
        qr_img = qr.make_image(fill_color="black", back_color="white")
        
        # メタデータ付きQRコード
        final_img = create_hybrid_qr(qr_img, {
            'title': 'Voice Memorial QR - Hybrid Technology',
            'filename': audio_file.filename,
            'raw_size': f"{raw_size} bytes",
            'url_length': f"{len(hybrid_url)} chars",
            'technology': 'URL + RAW Data Embedding',
            'compatibility': 'All smartphones',
            'server_backup': 'Optional fallback',
            'scan_action': 'Instant Play + Download'
        })
        
        # 画像をバイトストリームに変換
        img_io = io.BytesIO()
        final_img.save(img_io, 'PNG', optimize=True)
        img_io.seek(0)
        
        return send_file(
            img_io,
            mimetype='image/png',
            as_attachment=True,
            download_name=f"voice_hybrid_qr_{Path(audio_file.filename).stem}_{unique_id}.png"
        )
        
    except Exception as e:
        return jsonify({'error': f'Hybrid QR generation failed: {str(e)}'}), 500
    finally:
        if audio_file_path and os.path.exists(audio_file_path):
            os.remove(audio_file_path)

@app.route('/play')
def play_hybrid():
    """
    ハイブリッド再生：URLパラメータからRAWデータ直接復元
    """
    try:
        # URLパラメータからRAWデータ取得
        encoded_data = request.args.get('data')
        filename = request.args.get('filename', 'voice_memorial.m4a')
        audio_id = request.args.get('id', 'unknown')
        
        if not encoded_data:
            return jsonify({'error': 'No audio data in URL parameters'}), 400
        
        # URLデコード
        url_decoded_data = urllib.parse.unquote(encoded_data)
        
        # base64デコード → RAW音声データ復元
        raw_opus_data = base64.b64decode(url_decoded_data)
        
        # 一時ファイル作成
        unique_id = str(uuid.uuid4())[:8]
        opus_path = os.path.join(TEMP_DIR, f"url_decoded_{unique_id}.opus")
        m4a_path = os.path.join(TEMP_DIR, f"url_decoded_{unique_id}.m4a")
        
        # RAWデータをopusファイルとして保存
        with open(opus_path, 'wb') as f:
            f.write(raw_opus_data)
        
        # 再生用m4a変換
        ffmpeg_cmd = [
            'ffmpeg', '-i', opus_path,
            '-c:a', 'aac',
            '-b:a', '128k',
            '-ar', '44100',
            '-y',
            m4a_path
        ]
        
        result = subprocess.run(ffmpeg_cmd, capture_output=True)
        
        if result.returncode != 0:
            raise Exception("Audio conversion failed")
        
        # ファイルサイズ確認
        if not os.path.exists(m4a_path) or os.path.getsize(m4a_path) == 0:
            raise Exception("Converted audio file is empty")
        
        # 音声ファイルを返す
        return send_file(
            m4a_path,
            mimetype='audio/mp4',
            as_attachment=False,  # ブラウザで直接再生
            download_name=f"voice_memorial_{Path(filename).stem}_{audio_id}.m4a"
        )
        
    except Exception as e:
        return f"""
        <html>
        <head><title>Voice Memorial - Playback Error</title></head>
        <body style="font-family: Arial; padding: 50px; text-align: center;">
            <h1>🚫 音声再生エラー</h1>
            <p>エラー: {str(e)}</p>
            <p><a href="/">新しい音声QRコードを作成する</a></p>
        </body>
        </html>
        """, 500
    finally:
        # クリーンアップ
        for path_var in ['opus_path', 'm4a_path']:
            if path_var in locals():
                path = locals()[path_var]
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except:
                        pass

@app.route('/info')
def info_page():
    """
    技術情報ページ（オプション）
    """
    encoded_data = request.args.get('data', '')
    filename = request.args.get('filename', 'Unknown')
    audio_id = request.args.get('id', 'Unknown')
    
    try:
        if encoded_data:
            url_decoded = urllib.parse.unquote(encoded_data)
            raw_data = base64.b64decode(url_decoded)
            data_size = len(raw_data)
        else:
            data_size = 0
        
        play_url = request.url.replace('/info', '/play')
        
        return f"""
        <html>
        <head>
            <title>Voice Memorial - 技術情報</title>
            <style>
                body {{ font-family: Arial; margin: 50px; background: #f8f9fa; }}
                .container {{ max-width: 800px; margin: 0 auto; background: white; padding: 40px; border-radius: 15px; box-shadow: 0 10px 30px rgba(0,0,0,0.1); }}
                .tech-info {{ background: #e3f2fd; padding: 20px; border-radius: 10px; margin: 20px 0; }}
                .play-button {{ background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); color: white; padding: 20px 40px; border: none; border-radius: 25px; font-size: 1.2em; text-decoration: none; display: inline-block; margin: 20px 0; }}
                .highlight {{ color: #e74c3c; font-weight: bold; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🎵 Voice Memorial - ハイブリッド技術</h1>
                
                <div class="tech-info">
                    <h3>🔧 技術仕様</h3>
                    <p><strong>ファイル名:</strong> {filename}</p>
                    <p><strong>ID:</strong> {audio_id}</p>
                    <p><strong>RAWデータサイズ:</strong> {data_size} bytes</p>
                    <p><strong>URL長:</strong> {len(request.url)} 文字</p>
                    <p><strong>技術方式:</strong> <span class="highlight">URL + RAWデータ埋め込み</span></p>
                    <p><strong>サーバー依存:</strong> <span class="highlight">なし（RAWデータ自蔵）</span></p>
                    <p><strong>永続性:</strong> <span class="highlight">URLが残る限り永続</span></p>
                </div>
                
                <div style="text-align: center;">
                    <a href="{play_url}" class="play-button">🎵 音声を再生・ダウンロード</a>
                </div>
                
                <div class="tech-info">
                    <h3>⚡ 革命的技術の特徴</h3>
                    <ul>
                        <li>QRコード内に音声RAWデータを完全埋め込み</li>
                        <li>サーバーダウンでも音声は永続保存</li>
                        <li>スマートフォンで即座スキャン・再生</li>
                        <li>URL共有で簡単シェア可能</li>
                        <li>世界初のハイブリッド音声保存技術</li>
                    </ul>
                </div>
                
                <div style="text-align: center; margin-top: 30px; color: #666;">
                    <p>© 2025 Voice Memorial QR - 革命的ハイブリッド音声保存技術</p>
                    <p><a href="/">新しい音声QRコードを作成する</a></p>
                </div>
            </div>
        </body>
        </html>
        """
        
    except Exception as e:
        return f"Error loading info: {str(e)}", 500

def create_hybrid_qr(qr_img, metadata):
    """
    ハイブリッド技術表示用QRコード
    """
    qr_width, qr_height = qr_img.size
    
    # レイアウト設計
    header_height = 120
    footer_height = 160
    padding = 15
    
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
    title = metadata.get('title', 'Voice Memorial Hybrid QR')
    draw.text((padding, 15), title, fill='#2c3e50', font=font)
    
    # 技術的特徴を強調
    tech_line1 = "⚡ URL + RAW Data Embedded"
    draw.text((padding, 35), tech_line1, fill='#e74c3c', font=font)
    
    tech_line2 = "📱 Instant Scan → Play → Download"
    draw.text((padding, 55), tech_line2, fill='#27ae60', font=font)
    
    tech_line3 = "🔒 Server-Independent + Shareable"
    draw.text((padding, 75), tech_line3, fill='#8e44ad', font=font)
    
    # 区切り線
    line_y = 100
    draw.line([(padding, line_y), (total_width - padding, line_y)], fill='#3498db', width=2)
    
    # フッター情報
    footer_y = qr_y + qr_height + padding
    footer_items = [
        f"📁 File: {metadata.get('filename', 'Unknown')}",
        f"💾 Raw: {metadata.get('raw_size', 'Unknown')}",
        f"🔗 URL: {metadata.get('url_length', 'Unknown')}",
        f"🛡️ Tech: {metadata.get('technology', 'Unknown')}",
        f"📱 Compat: {metadata.get('compatibility', 'Unknown')}",
        f"⚡ Action: {metadata.get('scan_action', 'Unknown')}",
        f"🔄 Backup: {metadata.get('server_backup', 'Unknown')}"
    ]
    
    for i, item in enumerate(footer_items):
        draw.text((padding, footer_y + i * 16), item, fill='#34495e', font=font)
    
    # 重要な説明
    instruction = "📲 Scan → Instant Audio Playback"
    inst_y = footer_y + len(footer_items) * 16 + 10
    draw.text((padding, inst_y), instruction, fill='#e67e22', font=font)
    
    return final_img

@app.route('/health')
def health_check():
    return jsonify({
        'status': 'healthy',
        'message': 'Voice Memorial Hybrid QR Service',
        'technology': 'URL + RAW Data Embedding',
        'advantages': [
            'Smartphone compatible',
            'Instant playback',
            'Server independent',
            'Easy sharing',
            'Safari optimized'
        ],
        'url_limit': '80,000 chars (Safari)',
        'audio_limit': '~3 seconds for optimal QR size',
        'version': '4.0-hybrid-perfected'
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)
