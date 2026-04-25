"""
用户发件邮箱管理 API
支持邮箱绑定、验证、解绑、列表查询
M2: 邮箱绑定/验证/解绑/列表 API
"""
import random
import string
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, UserSenderBinding, EmailQuotaConfig, Notification
import boto3
from botocore.exceptions import ClientError

email_senders_bp = Blueprint('email_senders', __name__)


def generate_verification_code():
    """生成6位数字验证码"""
    return ''.join(random.choices(string.digits, k=6))


def check_email_exists_for_other_user(email, user_id):
    """检查邮箱是否已被其他用户绑定"""
    existing = UserSenderBinding.query.filter(
        UserSenderBinding.email == email,
        UserSenderBinding.user_id != user_id,
        UserSenderBinding.is_active == True
    ).first()
    return existing is not None


def get_or_create_default_quota():
    """获取或创建默认配额配置"""
    config = EmailQuotaConfig.query.filter_by(is_default=True).first()
    if not config:
        config = EmailQuotaConfig(
            name='free',
            daily_limit=current_app.config.get('DEFAULT_DAILY_QUOTA', 100),
            description='Free tier: 100 emails per day',
            is_default=True
        )
        db.session.add(config)
        db.session.commit()
    return config


def get_binding_quota_config(binding):
    """获取绑定的配额配置（代码层面关联，非数据库外键）"""
    if binding.quota_config_id:
        return EmailQuotaConfig.query.get(binding.quota_config_id)
    return None


@email_senders_bp.route('/senders', methods=['GET'])
@jwt_required()
def list_senders():
    """获取用户的发件邮箱列表"""
    uid = int(get_jwt_identity())
    
    bindings = UserSenderBinding.query.filter_by(
        user_id=uid,
        is_active=True
    ).order_by(UserSenderBinding.created_at.desc()).all()
    
    result = []
    for b in bindings:
        # 获取配额配置（代码层面关联查询）
        quota_config = None
        if b.quota_config_id:
            quota_config = EmailQuotaConfig.query.get(b.quota_config_id)
        
        data = {
            'id': b.id,
            'email': b.email,
            'email_type': b.email_type,
            'ses_identity_status': b.ses_identity_status,
            'is_default': b.is_default,
            'is_verified': b.ses_identity_status == 'verified',
            'daily_sent': b.daily_sent,
            'daily_limit': b.custom_daily_limit or (
                quota_config.daily_limit if quota_config
                else current_app.config.get('DEFAULT_DAILY_QUOTA', 100)
            ),
            'created_at': b.created_at.isoformat() if b.created_at else None
        }
        # 系统模式下显示真实邮箱
        if b.email_type == 'system' and b.real_email:
            data['real_email'] = b.real_email
        result.append(data)
    
    return jsonify({
        'senders': result,
        'mode': current_app.config.get('EMAIL_SENDER_MODE', 'personal'),
        'total': len(result)
    }), 200


@email_senders_bp.route('/senders', methods=['POST'])
@jwt_required()
def apply_sender():
    """申请绑定新邮箱（发送验证码）"""
    uid = int(get_jwt_identity())
    data = request.get_json()
    
    email = data.get('email', '').strip().lower()
    if not email:
        return jsonify(msg='请提供邮箱地址'), 400
    
    # 检查邮箱格式（简单检查）
    if '@' not in email or '.' not in email.split('@')[-1]:
        return jsonify(msg='邮箱格式不正确'), 400
    
    # 检查是否已被其他用户绑定
    if check_email_exists_for_other_user(email, uid):
        return jsonify(msg='该邮箱已被其他用户绑定'), 409
    
    # 检查当前用户是否已绑定该邮箱
    existing = UserSenderBinding.query.filter_by(
        user_id=uid,
        email=email,
        is_active=True
    ).first()
    
    if existing:
        if existing.ses_identity_status == 'verified':
            return jsonify(msg='该邮箱已绑定并验证'), 409
        else:
            # 重新发送验证码
            existing.verification_token = generate_verification_code()
            existing.token_expires_at = datetime.utcnow() + timedelta(minutes=10)
            db.session.commit()
            
            # TODO: 发送验证码邮件
            return jsonify({
                'msg': '验证码已重新发送',
                'email': email,
                'binding_id': existing.id,
                'expires_in': 600
            }), 200
    
    # personal 模式：需要 SES 验证
    sender_mode = current_app.config.get('EMAIL_SENDER_MODE', 'personal')
    
    if sender_mode == 'personal':
        # 调用 SES verify_email_identity
        try:
            client = boto3.client(
                'ses',
                region_name=current_app.config['AWS_REGION'],
                aws_access_key_id=current_app.config['AWS_ACCESS_KEY_ID'],
                aws_secret_access_key=current_app.config['AWS_SECRET_ACCESS_KEY']
            )
            client.verify_email_identity(EmailAddress=email)
        except ClientError as e:
            return jsonify(msg=f"SES验证请求失败: {e.response['Error']['Message']}"), 500
    
    # 创建绑定记录
    default_quota = get_or_create_default_quota()
    
    # 如果是第一个绑定，设为默认
    existing_count = UserSenderBinding.query.filter_by(
        user_id=uid,
        is_active=True
    ).count()
    
    binding = UserSenderBinding(
        user_id=uid,
        email=email,
        email_type=sender_mode,
        verification_token=generate_verification_code(),
        token_expires_at=datetime.utcnow() + timedelta(minutes=10),
        quota_config_id=default_quota.id,
        is_default=(existing_count == 0),  # 第一个设为默认
        ses_identity_status='pending' if sender_mode == 'personal' else 'verified'
    )
    
    db.session.add(binding)
    db.session.commit()
    
    # personal 模式下验证码通过 SES 验证邮件
    # TODO: 实际项目中需要给用户发送验证码邮件
    
    return jsonify({
        'msg': '绑定申请已提交，请查收验证邮件' if sender_mode == 'personal' else '绑定成功',
        'email': email,
        'binding_id': binding.id,
        'verification_required': sender_mode == 'personal',
        'expires_in': 600
    }), 201


@email_senders_bp.route('/senders/verify', methods=['POST'])
@jwt_required()
def verify_sender():
    """验证邮箱所有权（输入验证码）"""
    uid = int(get_jwt_identity())
    data = request.get_json()
    
    binding_id = data.get('binding_id')
    email = data.get('email', '').strip().lower()
    token = data.get('token', '').strip()
    
    if not binding_id or not email or not token:
        return jsonify(msg='请提供完整信息'), 400
    
    binding = UserSenderBinding.query.filter_by(
        id=binding_id,
        user_id=uid,
        email=email,
        is_active=True
    ).first()
    
    if not binding:
        return jsonify(msg='绑定记录不存在'), 404
    
    if binding.ses_identity_status == 'verified':
        return jsonify(msg='该邮箱已验证'), 200
    
    if binding.token_expires_at and binding.token_expires_at < datetime.utcnow():
        return jsonify(msg='验证码已过期，请重新申请'), 410
    
    if binding.verification_token != token:
        return jsonify(msg='验证码错误'), 400
    
    # 验证成功
    binding.ses_identity_status = 'verified'
    binding.ses_verified_at = datetime.utcnow()
    binding.verification_token = None
    binding.token_expires_at = None
    db.session.commit()
    
    return jsonify({
        'msg': '邮箱验证成功',
        'email': email,
        'verified_at': binding.ses_verified_at.isoformat()
    }), 200


@email_senders_bp.route('/senders/<int:binding_id>/resend', methods=['POST'])
@jwt_required()
def resend_verification(binding_id):
    """重新发送验证码"""
    uid = int(get_jwt_identity())
    
    binding = UserSenderBinding.query.filter_by(
        id=binding_id,
        user_id=uid,
        is_active=True
    ).first()
    
    if not binding:
        return jsonify(msg='绑定记录不存在'), 404
    
    if binding.ses_identity_status == 'verified':
        return jsonify(msg='该邮箱已验证'), 400
    
    # 重新生成验证码
    binding.verification_token = generate_verification_code()
    binding.token_expires_at = datetime.utcnow() + timedelta(minutes=10)
    db.session.commit()
    
    # personal 模式下重新调用 SES 验证
    if binding.email_type == 'personal':
        try:
            client = boto3.client(
                'ses',
                region_name=current_app.config['AWS_REGION'],
                aws_access_key_id=current_app.config['AWS_ACCESS_KEY_ID'],
                aws_secret_access_key=current_app.config['AWS_SECRET_ACCESS_KEY']
            )
            client.verify_email_identity(EmailAddress=binding.email)
        except ClientError as e:
            return jsonify(msg=f"SES验证请求失败: {e.response['Error']['Message']}"), 500
    
    return jsonify({
        'msg': '验证码已重新发送',
        'email': binding.email,
        'expires_in': 600
    }), 200


@email_senders_bp.route('/senders/<int:binding_id>', methods=['DELETE'])
@jwt_required()
def delete_sender(binding_id):
    """解绑邮箱"""
    uid = int(get_jwt_identity())
    
    binding = UserSenderBinding.query.filter_by(
        id=binding_id,
        user_id=uid,
        is_active=True
    ).first()
    
    if not binding:
        return jsonify(msg='绑定记录不存在'), 404
    
    # 不能删除默认发件邮箱
    if binding.is_default:
        # 检查是否有其他绑定
        other = UserSenderBinding.query.filter(
            UserSenderBinding.user_id == uid,
            UserSenderBinding.id != binding_id,
            UserSenderBinding.is_active == True
        ).first()
        if other:
            # 将另一个设为默认
            other.is_default = True
        else:
            return jsonify(msg='不能删除唯一的默认发件邮箱'), 400
    
    # 软删除
    binding.is_active = False
    binding.is_default = False
    db.session.commit()
    
    return jsonify({
        'msg': '邮箱已解绑',
        'email': binding.email
    }), 200


@email_senders_bp.route('/senders/<int:binding_id>/default', methods=['PUT'])
@jwt_required()
def set_default_sender(binding_id):
    """设为默认发件邮箱"""
    uid = int(get_jwt_identity())
    
    binding = UserSenderBinding.query.filter_by(
        id=binding_id,
        user_id=uid,
        is_active=True
    ).first()
    
    if not binding:
        return jsonify(msg='绑定记录不存在'), 404
    
    if binding.ses_identity_status != 'verified':
        return jsonify(msg='邮箱未验证，不能设为默认'), 400
    
    # 取消其他默认
    UserSenderBinding.query.filter_by(
        user_id=uid,
        is_default=True
    ).update({'is_default': False})
    
    # 设为默认
    binding.is_default = True
    db.session.commit()
    
    return jsonify({
        'msg': '已设为默认发件邮箱',
        'email': binding.email
    }), 200


@email_senders_bp.route('/quota', methods=['GET'])
@jwt_required()
def get_quota():
    """获取用户配额使用情况"""
    uid = int(get_jwt_identity())
    
    # 获取默认绑定
    binding = UserSenderBinding.query.filter_by(
        user_id=uid,
        is_default=True,
        is_active=True
    ).first()
    
    if not binding:
        # 使用系统默认配额
        default_limit = current_app.config.get('DEFAULT_DAILY_QUOTA', 100)
        return jsonify({
            'has_binding': False,
            'daily_limit': default_limit,
            'daily_sent': 0,
            'remaining': default_limit,
            'reset_at': None,
            'using_system_default': True
        }), 200
    
    # 计算剩余配额
    quota_config = None
    if binding.quota_config_id:
        quota_config = EmailQuotaConfig.query.get(binding.quota_config_id)
    
    limit = binding.custom_daily_limit or (
        quota_config.daily_limit if quota_config
        else current_app.config.get('DEFAULT_DAILY_QUOTA', 100)
    )
    remaining = max(0, limit - binding.daily_sent)
    
    # 配额重置时间
    reset_hour = current_app.config.get('QUOTA_RESET_HOUR', 0)
    now = datetime.utcnow()
    next_reset = now.replace(hour=reset_hour, minute=0, second=0, microsecond=0)
    if now >= next_reset:
        next_reset = next_reset + timedelta(days=1)
    
    return jsonify({
        'has_binding': True,
        'email': binding.email,
        'email_type': binding.email_type,
        'daily_limit': limit,
        'daily_sent': binding.daily_sent,
        'remaining': remaining,
        'reset_at': next_reset.isoformat(),
        'using_system_default': False
    }), 200
