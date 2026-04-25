"""
支付接口 - 预留功能
M8: 多支付服务商支持（用户可选支付方式）

说明:
- 当前为预留接口，框架已搭建
- 实际实现需根据选择的支付服务商接入SDK
- 支付方式为并列关系，用户支付时可选

支持的支付方式（预留）:
- 支付宝 (Alipay)
- 微信支付 (WeChat Pay)
- Stripe (国际信用卡)

状态: 接口已预留，功能待实现
"""

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, UserSubscription, EmailQuotaConfig

payment_bp = Blueprint('payment', __name__)


def get_available_payment_methods():
    """
    获取可用的支付方式列表
    根据.env配置返回启用的支付方式
    """
    methods = []
    
    if current_app.config.get('PAYMENT_ALIPAY_ENABLED'):
        methods.append({
            'id': 'alipay',
            'name': '支付宝',
            'icon': '/static/icons/alipay.svg',
            'description': '中国大陆用户推荐'
        })
    
    if current_app.config.get('PAYMENT_WECHAT_ENABLED'):
        methods.append({
            'id': 'wechat',
            'name': '微信支付',
            'icon': '/static/icons/wechat-pay.svg',
            'description': '微信扫码支付'
        })
    
    if current_app.config.get('PAYMENT_STRIPE_ENABLED'):
        methods.append({
            'id': 'stripe',
            'name': '国际信用卡',
            'icon': '/static/icons/stripe.svg',
            'description': '支持 Visa/Mastercard'
        })
    
    return methods


@payment_bp.route('/methods', methods=['GET'])
@jwt_required()
def get_payment_methods():
    """
    获取支持的支付方式
    前端在支付页面展示选项
    """
    # 检查是否启用了购买功能
    if not current_app.config.get('UPGRADE_FEATURE_ENABLED', False):
        return jsonify({
            'enabled': False,
            'msg': '购买功能未启用'
        }), 200
    
    methods = get_available_payment_methods()
    
    return jsonify({
        'enabled': True,
        'methods': methods
    }), 200


@payment_bp.route('/quota-configs', methods=['GET'])
@jwt_required()
def get_quota_configs():
    """
    获取可购买的配额配置
    """
    if not current_app.config.get('UPGRADE_FEATURE_ENABLED', False):
        return jsonify({
            'enabled': False,
            'msg': '购买功能未启用'
        }), 200
    
    configs = EmailQuotaConfig.query.filter(
        EmailQuotaConfig.price_monthly.isnot(None)
    ).order_by(EmailQuotaConfig.daily_limit).all()
    
    result = []
    for c in configs:
        result.append({
            'id': c.id,
            'name': c.name,
            'daily_limit': c.daily_limit,
            'description': c.description,
            'price_monthly': c.price_monthly,  # 分
            'price_yearly': c.price_yearly,    # 分
            'price_monthly_display': f"{c.price_monthly / 100:.2f}" if c.price_monthly else None,
            'price_yearly_display': f"{c.price_yearly / 100:.2f}" if c.price_yearly else None
        })
    
    return jsonify({
        'enabled': True,
        'configs': result
    }), 200


@payment_bp.route('/create-order', methods=['POST'])
@jwt_required()
def create_order():
    """
    创建支付订单（预留）
    
    Request Body:
        - quota_config_id: 购买的配额配置ID
        - payment_method: 支付方式 (alipay/wechat/stripe)
        - billing_cycle: 计费周期 (monthly/yearly)
    
    Response:
        - order_id: 订单ID
        - payment_url: 支付跳转URL（扫码支付则为二维码）
        - expires_at: 订单过期时间
    """
    if not current_app.config.get('UPGRADE_FEATURE_ENABLED', False):
        return jsonify(msg='购买功能未启用'), 403
    
    uid = int(get_jwt_identity())
    data = request.get_json()
    
    quota_config_id = data.get('quota_config_id')
    payment_method = data.get('payment_method')
    billing_cycle = data.get('billing_cycle', 'monthly')  # monthly/yearly
    
    # 参数检查
    if not quota_config_id or not payment_method:
        return jsonify(msg='参数不完整'), 400
    
    if payment_method not in ['alipay', 'wechat', 'stripe']:
        return jsonify(msg='不支持的支付方式'), 400
    
    # 检查支付方式是否启用
    method_enabled = {
        'alipay': current_app.config.get('PAYMENT_ALIPAY_ENABLED'),
        'wechat': current_app.config.get('PAYMENT_WECHAT_ENABLED'),
        'stripe': current_app.config.get('PAYMENT_STRIPE_ENABLED')
    }
    
    if not method_enabled.get(payment_method):
        return jsonify(msg='该支付方式未启用'), 400
    
    # 获取配额配置
    config = EmailQuotaConfig.query.get(quota_config_id)
    if not config:
        return jsonify(msg='配置不存在'), 404
    
    # 计算价格
    amount = config.price_monthly if billing_cycle == 'monthly' else config.price_yearly
    if not amount:
        return jsonify(msg='该计费周期不可用'), 400
    
    # TODO: 根据支付方式调用不同SDK创建订单
    # ==================== 预留实现 ====================
    
    if payment_method == 'alipay':
        # TODO: 接入支付宝SDK
        # from alipay import AliPay
        # ... 创建订单逻辑 ...
        return jsonify({
            'msg': '支付宝支付预留接口',
            'order_id': f'ORDER_ALIPAY_{uid}_{int(time.time())}',
            'payment_url': 'https://example.com/alipay/pay',
            'amount': amount,
            'expires_at': (datetime.utcnow() + timedelta(minutes=30)).isoformat()
        }), 200
    
    elif payment_method == 'wechat':
        # TODO: 接入微信支付SDK
        # import wechatpay
        # ... 创建订单逻辑 ...
        return jsonify({
            'msg': '微信支付预留接口',
            'order_id': f'ORDER_WECHAT_{uid}_{int(time.time())}',
            'qrcode_url': 'https://example.com/wechat/qr',
            'amount': amount,
            'expires_at': (datetime.utcnow() + timedelta(minutes=30)).isoformat()
        }), 200
    
    elif payment_method == 'stripe':
        # TODO: 接入Stripe SDK
        # import stripe
        # ... 创建Session逻辑 ...
        return jsonify({
            'msg': 'Stripe支付预留接口',
            'order_id': f'ORDER_STRIPE_{uid}_{int(time.time())}',
            'checkout_url': 'https://example.com/stripe/checkout',
            'amount': amount,
            'expires_at': (datetime.utcnow() + timedelta(minutes=30)).isoformat()
        }), 200
    
    return jsonify(msg='支付方式处理失败'), 500


@payment_bp.route('/webhook/<provider>', methods=['POST'])
def payment_webhook(provider):
    """
    支付回调接口（预留）
    
    各支付平台回调此接口通知支付结果
    
    Path:
        - provider: alipay / wechat / stripe
    
    Returns:
        - 返回平台要求的响应格式
    """
    current_app.logger.info(f"[Payment] Webhook received from {provider}")
    
    # TODO: 验证签名和回调数据
    # TODO: 更新订单状态
    # TODO: 激活用户订阅
    
    # 根据平台返回不同响应
    if provider == 'alipay':
        return 'success', 200  # 支付宝需要返回 'success'
    elif provider == 'wechat':
        return '<xml><return_code>SUCCESS</return_code></xml>', 200, {
            'Content-Type': 'application/xml'
        }
    elif provider == 'stripe':
        return '', 200
    
    return '', 400


@payment_bp.route('/orders', methods=['GET'])
@jwt_required()
def get_orders():
    """
    获取用户订单列表（预留）
    """
    if not current_app.config.get('UPGRADE_FEATURE_ENABLED', False):
        return jsonify({
            'enabled': False,
            'msg': '购买功能未启用'
        }), 200
    
    uid = int(get_jwt_identity())
    
    # TODO: 查询用户订阅记录
    subscriptions = UserSubscription.query.filter_by(
        user_id=uid
    ).order_by(UserSubscription.created_at.desc()).limit(20).all()
    
    result = []
    for sub in subscriptions:
        result.append({
            'id': sub.id,
            'quota_config_id': sub.quota_config_id,
            'payment_provider': sub.payment_provider,
            'amount_paid': sub.amount_paid / 100 if sub.amount_paid else 0,  # 转为元
            'status': sub.status,
            'started_at': sub.started_at.isoformat() if sub.started_at else None,
            'expires_at': sub.expires_at.isoformat() if sub.expires_at else None,
            'created_at': sub.created_at.isoformat() if sub.created_at else None
        })
    
    return jsonify({
        'enabled': True,
        'orders': result
    }), 200


# 预留：支付实现指南
"""
============================================
支付功能实现指南（预留）
============================================

1. 安装依赖
----------------

# 支付宝
pip install python-alipay-sdk

# 微信支付
pip install wechatpayv3

# Stripe
pip install stripe


2. 配置.env
----------------

# 支付宝
PAYMENT_ALIPAY_ENABLED=true
PAYMENT_ALIPAY_APP_ID=your-app-id
PAYMENT_ALIPAY_PRIVATE_KEY=your-private-key
PAYMENT_ALIPAY_PUBLIC_KEY=alipay-public-key

# 微信支付
PAYMENT_WECHAT_ENABLED=true
PAYMENT_WECHAT_APP_ID=your-app-id
PAYMENT_WECHAT_MCH_ID=your-mch-id
PAYMENT_WECHAT_API_KEY=your-api-key

# Stripe
PAYMENT_STRIPE_ENABLED=true
PAYMENT_STRIPE_SECRET_KEY=sk_test_xxx
PAYMENT_STRIPE_WEBHOOK_SECRET=whsec_xxx


3. 接入示例
----------------

# 支付宝
from alipay import AliPay

alipay = AliPay(
    appid=app.config['PAYMENT_ALIPAY_APP_ID'],
    app_notify_url="https://yourdomain.com/api/payment/webhook/alipay",
    app_private_key_string=app.config['PAYMENT_ALIPAY_PRIVATE_KEY'],
    alipay_public_key_string=app.config['PAYMENT_ALIPAY_PUBLIC_KEY'],
    sign_type="RSA2"
)

# 创建订单
order_string = alipay.api_alipay_trade_page_pay(
    out_trade_no=order_id,
    total_amount=amount / 100,  # 转为元
    subject=f"MailFlow Upgrade - {config.name}",
    return_url="https://yourdomain.com/payment/success",
    notify_url="https://yourdomain.com/api/payment/webhook/alipay"
)

# 微信支付
import wechatpayv3

wxpay = wechatpayv3.WeChatPay(
    mchid=app.config['PAYMENT_WECHAT_MCH_ID'],
    private_key=private_key,
    cert_serial_no=cert_serial,
    apiv3_key=app.config['PAYMENT_WECHAT_API_KEY'],
    appid=app.config['PAYMENT_WECHAT_APP_ID']
)

# Stripe
import stripe

stripe.api_key = app.config['PAYMENT_STRIPE_SECRET_KEY']

session = stripe.checkout.Session.create(
    payment_method_types=['card'],
    line_items=[{
        'price_data': {
            'currency': 'usd',
            'product_data': {'name': f'MailFlow {config.name}'},
            'unit_amount': amount,  # 分
        },
        'quantity': 1,
    }],
    mode='subscription',
    success_url='https://yourdomain.com/payment/success',
    cancel_url='https://yourdomain.com/payment/cancel',
)


4. 前端接入
----------------

# 支付方式选择
用户选择配置 → 选择支付方式 → 创建订单 → 跳转支付

# 支付结果
支付宝/Stripe: 同步回调 + 异步通知
微信支付: 扫码支付 + 异步通知

============================================
"""

from datetime import datetime, timedelta
import time
