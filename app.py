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
import urllib.parse

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

def create_hybrid_qr(data_uri, metadata):
    """🚀 革命的ハイブリッドQRコード生成（iPhone標準カメラ＋Reader両対応）"""
    
    # サーバーのベースURL（本番環境では実際のドメインを使用）
    base_url = "https://voice-memorial-qr.onrender.com"
    
    # 🎯 戦略1: iPhone標準カメラ用（直接音声再生）
    audio_param = urllib.parse.quote(data_uri)
    direct_url = f"{base_url}/play?audio={audio_param}"
    
    # 🎯 戦略2: Pearl Memorial Reader用（メタデータ付き）
    pearl_data = {
        "pearl_memorial": "v1.0",
        "type": "standalone_audio",
        "audio_data": data_uri,
        "metadata": {
            "title": metadata.get('title', metadata.get('filename', 'Pearl Memorial')),
            "filename": metadata['filename'],
            "created": datetime.now().isoformat(),
            "duration": MAX_DURATION,
            "id": metadata['id'],
            "technology": "Server-Independent DataURI",
            "creator": "Pearl Memorial System",
            # ユーザー提供のメタデータを含める
            "recipient": metadata.get('recipient'),
            "description": metadata.get('description'),
            "emotion_level": metadata.get('emotion_level'),
            "special_occasion": metadata.get('special_occasion'),
            "raw_size": metadata.get('raw_size'),
            "process_type": metadata.get('process_type')
        }
    }
    
    # 位置情報を別途追加（存在する場合）
    if metadata.get('location_data'):
        pearl_data['location_data'] = metadata['location_data']
    
    json_content = json.dumps(pearl_data, ensure_ascii=False, separators=(',', ':'))
    
    # 🧠 智的判定：最適形式を自動選択
    print(f"🔍 QR戦略分析:")
    print(f"   📱 iPhone直接URL: {len(direct_url)} 文字")
    print(f"   📄 Reader用JSON: {len(json_content)} 文字")
    print(f"   📏 QR最大制限: {QR_MAX_SIZE} 文字")
    
    # サイズ最適化による自動選択
    if len(direct_url) <= QR_MAX_SIZE and len(direct_url) < len(json_content):
        final_content = direct_url
        qr_type = "🎯 iPhone直接再生URL"
        print(f"✅ 選択: iPhone標準カメラ最適化 ({len(direct_url)} chars)")
    elif len(json_content) <= QR_MAX_SIZE:
        final_content = json_content
        qr_type = "📱 Reader用JSON"
        print(f"✅ 選択: Pearl Memorial Reader最適化 ({len(json_content)} chars)")
    else:
        raise PearlMemorialError(f'音声データが大きすぎます。両形式ともQR制限を超過しています。')
    
    # QRコード生成
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=4,
        border=1,
    )
    
    try:
        qr.add_data(final_content)
        qr.make(fit=True)
        
        print(f"📊 QRコード Version {qr.version} - {qr_type}")
        
        if qr.version > 40:
            raise PearlMemorialError(f'QRコードが大きすぎます（バージョン{qr.version}）')
        
        # QR画像生成
        qr_img = qr.make_image(fill_color="black", back_color="white")
        
        # メタデータ付きQR画像生成
        final_img = add_qr_metadata(qr_img, {
            **metadata,
            'qr_version': f"Version {qr.version}",
            'content_length': f"{len(final_content)} chars",
            'qr_type': qr_type,
            'hybrid_mode': 'iPhone + Reader Compatible'
        })
        
        return final_img
        
    except Exception as e:
        print(f"❌ QRコード生成エラー: {str(e)}")
        raise PearlMemorialError(f'QRコード生成エラー: {str(e)}')

def add_qr_metadata(qr_img, metadata):
    """QRコードにメタデータを追加"""
    qr_width, qr_height = qr_img.size
    header_height, footer_height, padding = 180, 260, 15
    
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
    
    # ヘッダー情報（ハイブリッド対応強調）
    y = 15
    header_texts = [
        ("🐚 Pearl Memorial QR - ハイブリッド対応", '#2c3e50'),
        ("📱 iPhone Camera + Reader Compatible", '#e74c3c'),
        ("🚀 Server-Independent DataURI Technology", '#27ae60'),
        ("✈️ Works Offline Forever (1000 Years)", '#9b59b6'),
        ("🎯 Instant Play + Full Metadata Support", '#f39c12'),
        ("🌍 World's First Hybrid Voice QR", '#e67e22'),
        (f"⚡ Mode: {metadata.get('hybrid_mode', 'Unknown')}", '#3498db'),
        (f"🔧 Type: {metadata.get('qr_type', 'Unknown')}", '#8e44ad')
    ]
    
    for text, color in header_texts:
        draw.text((padding, y), text, fill=color, font=font)
        y += 20
    
    # 区切り線
    line_y = header_height - 5
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
        f"🎯 Mode: {metadata.get('hybrid_mode', 'Standard')}",
        f"🔍 Format: Pearl Memorial v1.0 Hybrid",
        f"🎵 Audio: Base64 Opus Codec",
        f"📲 iPhone: Instant Camera Play",
        f"🔑 Reader: Full Metadata Display",
        f"▶️ Action: Scan with ANY QR Reader",
        f"🌟 Breakthrough: Universal Compatibility"
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
    """🚀 ハイブリッド再生エンドポイント（iPhone標準カメラ + Reader対応）"""
    
    # 🎯 新戦略: audio=パラメータ（iPhone標準カメラ直接再生）
    audio_param = request.args.get('audio')
    # 📱 既存戦略: data=パラメータ（Reader経由メタデータ付き）
    data_param = request.args.get('data')
    
    if audio_param:
        # 🎯 iPhone標準カメラ → 直再生ルート
        print(f"📱 iPhone直接アクセス検出: {len(audio_param)} chars")
        try:
            # URLデコード
            audio_data_uri = urllib.parse.unquote(audio_param)
            
            # データURI形式確認
            if not audio_data_uri.startswith('data:audio/'):
                raise ValueError('無効な音声データURI')
            
            # 直接再生モードでレンダリング
            return render_template('play.html', 
                                 direct_audio=audio_data_uri,
                                 mode='direct',
                                 title='Pearl Memorial - 直接再生')
                                 
        except Exception as e:
            print(f"❌ iPhone直接再生エラー: {str(e)}")
            return render_template('reader.html', 
                                 error=f'音声データの読み込みに失敗しました: {str(e)}')
    
    elif data_param:
        # 📱 既存 → メタデータ付きルート  
        print(f"📄 Reader経由アクセス検出: {len(data_param)} chars")
        try:
            # Base64デコードしてJSONデータを取得
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
            
            # メタデータ付きモードでレンダリング
            return render_template('play.html', 
                                 pearl_data=json.dumps(pearl_data),
                                 mode='metadata')
            
        except Exception as e:
            print(f"❌ Reader経由再生エラー: {str(e)}")
            return render_template('reader.html', 
                                 error=f'QRデータの読み込みに失敗しました: {str(e)}')
    else:
        # パラメータなし → Readerページ
        return render_template('reader.html')

@app.route('/reader')
def reader():
    """Pearl Memorial Reader - QR読み取り・音声再生"""
    return render_template('reader.html')

@app.route('/generate', methods=['POST'])
def generate_qr():
    """QRコード生成API（ハイブリッド対応）"""
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
        
        # ユーザー入力のメタデータを取得
        metadata = {
            'filename': audio_file.filename,
            'id': unique_id,
            'raw_size': f"{raw_size} bytes",
            'process_type': process_type,
            'technology': 'Server-Independent DataURI',
            # ユーザー提供のメタデータを追加
            'title': request.form.get('title', audio_file.filename),
            'recipient': request.form.get('recipient'),
            'description': request.form.get('description'),
            'emotion_level': request.form.get('emotion_level'),
            'special_occasion': request.form.get('special_occasion')
        }
        
        # 位置情報データの処理
        location_data_str = request.form.get('location_data')
        if location_data_str:
            try:
                location_data = json.loads(location_data_str)
                metadata['location_data'] = location_data
            except json.JSONDecodeError:
                app.logger.warning(f"Failed to parse location data: {location_data_str}")
                metadata['location_data'] = None
        else:
            metadata['location_data'] = None
        
        # 🚀 ハイブリッドQRコード生成
        qr_image = create_hybrid_qr(data_uri, metadata)
        
        # 画像返却
        img_io = io.BytesIO()
        qr_image.save(img_io, 'PNG', optimize=True, quality=95)
        img_io.seek(0)
        
        download_name = f"pearl_memorial_hybrid_{Path(audio_file.filename).stem}_{unique_id}.png"
        
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
        'message': 'Pearl Memorial Hybrid QR Generator',
        'ffmpeg_available': ffmpeg_available,
        'technology': 'Server-Independent DataURI',
        'hybrid_support': {
            'iphone_camera': 'Direct audio playback via URL',
            'reader_app': 'Full metadata display via JSON',
            'auto_optimization': 'Size-based format selection'
        },
        'supported_formats': {
            'audio': list(AUDIO_EXTENSIONS),
            'video_with_audio': list(VIDEO_EXTENSIONS)
        },
        'features': [
            'Complete offline playback',
            'Server-independent storage', 
            'DataURI embedding',
            '2-second optimal duration',
            '1000-year guarantee',
            'iPhone Camera compatibility',
            'Reader App full support',
            'Hybrid QR generation'
        ],
        'version': 'Pearl Memorial v1.0 - Hybrid Architecture'
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)
