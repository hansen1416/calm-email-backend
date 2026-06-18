"""
Brand Image — 图片存储接口（合成由前端 Canvas 完成）
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from config import Config
import io
import uuid
from pathlib import Path

brand_bp = Blueprint('brand', __name__)

# ── 渐变配色（供前端展示用） ──
GRADIENT_COLORS = [
    { 'id': 'gradient-blue',    'name': 'Blue',    'color1': '#667eea', 'color2': '#764ba2' },
    { 'id': 'gradient-green',   'name': 'Green',   'color1': '#11998e', 'color2': '#38ef7d' },
    { 'id': 'gradient-warm',    'name': 'Warm',    'color1': '#f5af19', 'color2': '#f12711' },
    { 'id': 'gradient-sunset',  'name': 'Sunset',  'color1': '#ff6b6b', 'color2': '#c44569' },
    { 'id': 'gradient-ocean',   'name': 'Ocean',   'color1': '#1e90ff', 'color2': '#00ced1' },
    { 'id': 'gradient-forest',  'name': 'Forest',  'color1': '#2e7d32', 'color2': '#66bb6a' },
    { 'id': 'gradient-cotton',  'name': 'Cotton',  'color1': '#f8bbd0', 'color2': '#e1bee7' },
    { 'id': 'gradient-night',   'name': 'Night',   'color1': '#283593', 'color2': '#1a237e' },
    { 'id': 'gradient-cherry',  'name': 'Cherry',  'color1': '#f857a6', 'color2': '#ff5858' },
    { 'id': 'gradient-amber',   'name': 'Amber',   'color1': '#ffb347', 'color2': '#ffcc33' },
    { 'id': 'gradient-peace',   'name': 'Peace',   'color1': '#00b4db', 'color2': '#0083b0' },
    { 'id': 'gradient-lavender', 'name': 'Lavender', 'color1': '#ee9ca7', 'color2': '#ffdde1' },
]


@brand_bp.route('/templates', methods=['GET'])
@jwt_required()
def list_templates():
    return jsonify(GRADIENT_COLORS), 200


@brand_bp.route('/synthesize', methods=['POST'])
@jwt_required()
def synthesize():
    """接收前端合成好的 PNG 图片，存储并返回 URL"""
    uid = int(get_jwt_identity())

    if 'image' not in request.files:
        return jsonify(msg='请上传合成图片'), 400

    try:
        img_file = request.files['image']
        buf = io.BytesIO(img_file.read())

        storage = Config.BRAND_STORAGE

        if storage == 's3':
            aws_key = Config.AWS_ACCESS_KEY_ID
            aws_secret = Config.AWS_SECRET_ACCESS_KEY
            if not aws_key or not aws_secret:
                return jsonify(msg='S3 存储模式但缺少 AWS 凭证配置'), 500
            import boto3
            s3 = boto3.client('s3',
                              region_name=Config.AWS_REGION,
                              aws_access_key_id=aws_key,
                              aws_secret_access_key=aws_secret)
            filename = f'brand/{uid}/{uuid.uuid4().hex}.png'
            s3.upload_fileobj(buf, Config.BRAND_S3_BUCKET, filename,
                              ExtraArgs={'ContentType': 'image/png'})
            url = f'https://{Config.BRAND_S3_BUCKET}.s3.{Config.AWS_REGION}.amazonaws.com/{filename}'
        else:
            local_dir = Path(__file__).parent.parent / Config.BRAND_LOCAL_DIR
            local_dir.mkdir(parents=True, exist_ok=True)
            filename = f'{uuid.uuid4().hex}.png'
            with open(local_dir / filename, 'wb') as f:
                f.write(buf.getvalue())
            url = f'{request.host_url.rstrip("/")}/static/brand/{filename}'

        return jsonify({'url': url}), 200

    except Exception as e:
        return jsonify(msg=f'存储失败: {str(e)}'), 500