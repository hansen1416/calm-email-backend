"""
支付接口 - Stripe 英国 + 全欧洲
M11: Stripe Payment Integration

说明:
- Stripe Checkout Session 模式，无需自建支付页面
- 一个 STRIPE_MODE 开关切换 test ↔ live
- Webhook 自动处理订阅生命周期（创建/续费/取消/失败）
- 货币: GBP (英镑)，覆盖英国 + 全欧洲支付方式

支付方式（全欧洲覆盖）:
- card, link (全欧洲)
- bacs_debit (英国)
- sepa_debit (欧元区)
- ideal (荷兰), bancontact (比利时), sofort (德/奥), eps (奥), p24 (波兰), giropay (德国)
"""

import stripe as stripe_lib
import logging
import json
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, User, UserSubscription, EmailQuotaConfig, UserSenderBinding, Notification

payment_bp = Blueprint('payment', __name__)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stripe 配置
# ---------------------------------------------------------------------------

PAYMENT_METHODS_SUBSCRIPTION = [
    'card',         # Visa/Mastercard (全欧洲)
    'link',         # Stripe 快捷支付 (全欧洲)
    'bacs_debit',   # 英国银行直接借记
    'sepa_debit',   # SEPA 欧元区直接借记
    'ideal',        # 荷兰 (60%+ 市场份额)
]


def _get_stripe():
    """根据 STRIPE_MODE 返回对应模式 key"""
    mode = current_app.config.get('STRIPE_MODE', 'test')
    if mode == 'live':
        key = current_app.config.get('STRIPE_LIVE_SECRET_KEY', '')
    else:
        key = current_app.config.get('STRIPE_TEST_SECRET_KEY', '')
    stripe_lib.api_key = key
    return stripe_lib


def _get_webhook_secret():
    """获取对应模式的 webhook secret"""
    mode = current_app.config.get('STRIPE_MODE', 'test')
    if mode == 'live':
        return current_app.config.get('STRIPE_LIVE_WEBHOOK_SECRET', '')
    return current_app.config.get('STRIPE_TEST_WEBHOOK_SECRET', '')


def _update_user_quota(uid, quota_config_id):
    """更新用户所有发件绑定的配额配置"""
    bindings = UserSenderBinding.query.filter_by(user_id=uid, is_active=True).all()
    for b in bindings:
        b.quota_config_id = quota_config_id
    db.session.commit()


def _cancel_old_subscriptions(uid):
    """取消用户旧的有效订阅"""
    old_subs = UserSubscription.query.filter_by(user_id=uid, status='paid').all()
    for s in old_subs:
        s.status = 'cancelled'
    db.session.commit()

# ---------------------------------------------------------------------------
# 支付方式
# ---------------------------------------------------------------------------

def get_available_payment_methods():
    """获取可用的支付方式列表"""
    methods = []
    if current_app.config.get('PAYMENT_ALIPAY_ENABLED'):
        methods.append({
            'id': 'alipay', 'name': '\u652f\u4ed8\u5b9d',
            'icon': '/static/icons/alipay.svg',
            'description': '\u4e2d\u56fd\u5927\u9646\u7528\u6237\u63a8\u8350'
        })
    if current_app.config.get('PAYMENT_WECHAT_ENABLED'):
        methods.append({
            'id': 'wechat', 'name': '\u5fae\u4fe1\u652f\u4ed8',
            'icon': '/static/icons/wechat-pay.svg',
            'description': '\u5fae\u4fe1\u626b\u7801\u652f\u4ed8'
        })
    if current_app.config.get('PAYMENT_STRIPE_ENABLED'):
        methods.append({
            'id': 'stripe', 'name': 'Card / Bank Transfer',
            'icon': '/static/icons/stripe.svg',
            'description': 'UK & Europe (Visa/Mastercard/SEPA/iDEAL...)'
        })
    return methods


@payment_bp.route('/methods', methods=['GET'])
@jwt_required()
def get_payment_methods():
    if not current_app.config.get('UPGRADE_FEATURE_ENABLED', False):
        return jsonify({'enabled': False, 'msg': 'Payment not enabled'}), 200
    methods = get_available_payment_methods()
    return jsonify({'enabled': True, 'methods': methods}), 200


@payment_bp.route('/quota-configs', methods=['GET'])
@jwt_required()
def get_quota_configs():
    if not current_app.config.get('UPGRADE_FEATURE_ENABLED', False):
        return jsonify({'enabled': False, 'msg': 'Payment not enabled'}), 200
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
            'price_monthly': c.price_monthly,
            'price_yearly': c.price_yearly,
            'price_monthly_display': f"\u00a3{c.price_monthly / 100:.2f}" if c.price_monthly else None,
            'price_yearly_display': f"\u00a3{c.price_yearly / 100:.2f}" if c.price_yearly else None,
        })
    return jsonify({'enabled': True, 'configs': result}), 200


@payment_bp.route('/stripe/publishable-key', methods=['GET'])
@jwt_required()
def get_publishable_key():
    """前端获取 Stripe publishable key（按模式返回）"""
    mode = current_app.config.get('STRIPE_MODE', 'test')
    if mode == 'live':
        key = current_app.config.get('STRIPE_LIVE_PUBLISHABLE_KEY', '')
    else:
        key = current_app.config.get('STRIPE_TEST_PUBLISHABLE_KEY', '')
    return jsonify({'key': key, 'mode': mode}), 200

# ---------------------------------------------------------------------------
# 创建 Stripe Checkout Session
# ---------------------------------------------------------------------------

@payment_bp.route('/create-order', methods=['POST'])
@jwt_required()
def create_order():
    if not current_app.config.get('UPGRADE_FEATURE_ENABLED', False):
        return jsonify(msg='Payment not enabled'), 403

    uid = int(get_jwt_identity())
    data = request.get_json()

    quota_config_id = data.get('quota_config_id')
    payment_method = data.get('payment_method')
    billing_cycle = data.get('billing_cycle', 'monthly')

    if not quota_config_id or not payment_method:
        return jsonify(msg='Missing parameters'), 400

    if payment_method not in ['stripe']:
        return jsonify(msg='Unsupported payment method'), 400

    if not current_app.config.get('PAYMENT_STRIPE_ENABLED'):
        return jsonify(msg='Stripe not enabled'), 400

    config = EmailQuotaConfig.query.get(quota_config_id)
    if not config:
        return jsonify(msg='Plan not found'), 404

    amount = config.price_monthly if billing_cycle == 'monthly' else config.price_yearly
    if not amount:
        return jsonify(msg='Billing cycle not available'), 400

    stripe = _get_stripe()
    user = User.query.get(uid)
    domain_url = current_app.config.get('APP_URL', 'http://localhost:5173')

    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=PAYMENT_METHODS_SUBSCRIPTION,
            line_items=[{
                'price_data': {
                    'currency': 'gbp',
                    'product_data': {
                        'name': f'MailFlow {config.name}',
                        'description': f'{config.daily_limit} emails/day - {config.description or ""}',
                    },
                    'recurring': {
                        'interval': 'month' if billing_cycle == 'monthly' else 'year',
                    },
                    'unit_amount': amount,
                },
                'quantity': 1,
            }],
            mode='subscription',
            subscription_data={
                'metadata': {
                    'user_id': str(uid),
                    'quota_config_id': str(quota_config_id),
                    'plan': config.name,
                },
                'trial_period_days': 7,
            },
            billing_address_collection='required',
            tax_id_collection={'enabled': True},
            automatic_tax={'enabled': True},
            customer_email=user.email if user else None,
            success_url=f'{domain_url}/#/email-senders?session_id={{CHECKOUT_SESSION_ID}}&status=success',
            cancel_url=f'{domain_url}/#/email-senders?status=cancelled',
            locale='en-GB',
        )

        logger.info(f"[Stripe] Checkout Session created: {checkout_session.id} for user {uid}")

        return jsonify({
            'order_id': checkout_session.id,
            'checkout_url': checkout_session.url,
            'amount': amount,
            'currency': 'gbp',
        }), 200

    except stripe_lib.error.StripeError as e:
        logger.error(f"[Stripe] Error creating session: {str(e)}")
        return jsonify(msg=f'Stripe error: {str(e)}'), 500

# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------

@payment_bp.route('/webhook/<provider>', methods=['POST'])
def payment_webhook(provider):
    if provider == 'stripe':
        return _stripe_webhook()
    # Alipay/WeChat 预留
    if provider == 'alipay':
        return 'success', 200
    if provider == 'wechat':
        return '<xml><return_code>SUCCESS</return_code></xml>', 200, {'Content-Type': 'application/xml'}
    return '', 400


def _stripe_webhook():
    """Stripe Webhook 处理"""
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get('Stripe-Signature')

    webhook_secret = _get_webhook_secret()
    if not webhook_secret:
        logger.error("[Stripe] Webhook secret not configured")
        return '', 400

    try:
        event = stripe_lib.Webhook.construct_event(payload, sig_header, webhook_secret)
    except ValueError:
        logger.error("[Stripe] Invalid payload")
        return '', 400
    except stripe_lib.error.SignatureVerificationError:
        logger.error("[Stripe] Invalid signature")
        return '', 400

    event_type = event['type']
    logger.info(f"[Stripe] Webhook received: {event_type}")

    try:
        if event_type == 'checkout.session.completed':
            _on_checkout_completed(event['data']['object'])
        elif event_type == 'customer.subscription.updated':
            _on_subscription_updated(event['data']['object'])
        elif event_type == 'customer.subscription.deleted':
            _on_subscription_deleted(event['data']['object'])
        elif event_type in ('invoice.paid', 'invoice.payment_succeeded'):
            _on_invoice_paid(event['data']['object'])
        elif event_type == 'invoice.payment_failed':
            _on_payment_failed(event['data']['object'])
        # 以下事件无需处理，Stripe 会自动处理
        # invoice.created, invoice.finalized, invoice.upcoming,
        # customer.created, customer.updated, payment_method.attached,
        # setup_intent.created, setup_intent.succeeded, customer.subscription.created
    except Exception as e:
        logger.error(f"[Stripe] Error processing {event_type}: {str(e)}", exc_info=True)
        return '', 500

    return '', 200


def _on_checkout_completed(session):
    """支付完成 → 激活订阅"""
    # stripe.listen 转发的 webhook event['data']['object'] 可能是 dict 或 StripeObject
    subscription_id = session.get('subscription') if isinstance(session, dict) else str(session['subscription'])

    if not subscription_id:
        logger.error("[Stripe] No subscription_id in session")
        return

    # 通过 Stripe API 获取 subscription 详情来拿 metadata
    stripe = _get_stripe()
    try:
        stripe_sub = stripe.Subscription.retrieve(str(subscription_id))
        # StripeObject['metadata'] 返回 StripeObject，用 dict() 直接转会触发 KeyError
        # 正确做法：先转 JSON str 再 parse
        metadata = json.loads(str(stripe_sub['metadata']))
    except Exception as e:
        logger.error(f"[Stripe] Failed to retrieve subscription {subscription_id}: {repr(e)}")
        import traceback
        traceback.print_exc()
        return

    uid = int(metadata.get('user_id', 0))
    quota_config_id = int(metadata.get('quota_config_id', 0))
    plan_name = metadata.get('plan', 'unknown')

    if not uid:
        logger.error("[Stripe] No user_id in subscription metadata")
        return

    # 取消旧订阅
    _cancel_old_subscriptions(uid)

    # 创建新订阅
    amount = getattr(session, 'amount_total', None) or 0
    sub = UserSubscription(
        user_id=uid,
        quota_config_id=quota_config_id,
        payment_provider='stripe',
        payment_order_id=str(subscription_id),
        amount_paid=amount or 0,
        status='paid',
        started_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(days=30),
    )
    db.session.add(sub)

    # 更新用户配额
    _update_user_quota(uid, quota_config_id)

    # 发送通知
    notification = Notification(
        user_id=uid,
        type='subscription',
        title='Subscription Activated',
        content=f'Your MailFlow {plan_name} plan is now active. Enjoy {_get_plan_quota(quota_config_id)} emails/day.',
    )
    db.session.add(notification)
    db.session.commit()

    logger.info(f"[Stripe] Subscription activated: user={uid} plan={plan_name}")


def _on_subscription_updated(subscription):
    """订阅状态变更"""
    stripe_sub_id = str(getattr(subscription, 'id', ''))
    sub = UserSubscription.query.filter_by(
        payment_order_id=stripe_sub_id
    ).filter(UserSubscription.status.in_(['paid', 'cancelling'])).first()
    if sub:
        stripe_status = getattr(subscription, 'status', '')
        cancel_at_period = getattr(subscription, 'cancel_at_period_end', False)
        current_period_end = getattr(subscription, 'current_period_end', None)

        if cancel_at_period and sub.status != 'cancelling':
            sub.status = 'cancelling'
        if stripe_status == 'active' and not cancel_at_period:
            sub.status = 'paid'
        if current_period_end:
            sub.expires_at = datetime.utcfromtimestamp(current_period_end)

        db.session.commit()
        logger.info(f"[Stripe] Subscription updated: {stripe_sub_id} status={stripe_status} cancel_at_period_end={cancel_at_period}")


def _on_subscription_deleted(subscription):
    """订阅取消 → 降级为 Free"""
    stripe_sub_id = str(getattr(subscription, 'id', ''))
    sub = UserSubscription.query.filter_by(
        payment_order_id=stripe_sub_id
    ).filter(UserSubscription.status.in_(['paid', 'cancelling'])).first()
    if sub:
        sub.status = 'cancelled'
        sub.expires_at = datetime.utcnow()

        # 降级到 Free 配额
        free_config = EmailQuotaConfig.query.filter_by(is_default=True).first()
        if free_config:
            _update_user_quota(sub.user_id, free_config.id)

        # 通知用户
        notification = Notification(
            user_id=sub.user_id,
            type='subscription',
            title='Subscription Cancelled',
            content='Your subscription has been cancelled. You have been downgraded to the Free plan.',
        )
        db.session.add(notification)
        db.session.commit()
        logger.info(f"[Stripe] Subscription cancelled: {stripe_sub_id}")


def _on_invoice_paid(invoice):
    """续费发票支付成功 → 延长过期时间"""
    stripe_sub_id = str(getattr(invoice, 'subscription', ''))
    if not stripe_sub_id:
        return
    sub = UserSubscription.query.filter_by(
        payment_order_id=stripe_sub_id, status='paid'
    ).first()
    if sub:
        sub.expires_at = datetime.utcnow() + timedelta(days=30)
        db.session.commit()
        logger.info(f"[Stripe] Invoice paid: user={sub.user_id}")


def _on_payment_failed(invoice):
    """支付失败 → 通知用户"""
    stripe_sub_id = str(getattr(invoice, 'subscription', ''))
    sub = UserSubscription.query.filter_by(
        payment_order_id=stripe_sub_id, status='paid'
    ).first()
    if sub:
        notification = Notification(
            user_id=sub.user_id,
            type='subscription',
            title='Payment Failed',
            content='Your latest payment was unsuccessful. Please update your payment method to avoid service interruption.',
        )
        db.session.add(notification)
        db.session.commit()
        logger.warning(f"[Stripe] Payment failed: user={sub.user_id}")

# ---------------------------------------------------------------------------
# 用户订单/订阅查询
# ---------------------------------------------------------------------------

@payment_bp.route('/orders', methods=['GET'])
@jwt_required()
def get_orders():
    if not current_app.config.get('UPGRADE_FEATURE_ENABLED', False):
        return jsonify({'enabled': False, 'msg': 'Payment not enabled'}), 200

    uid = int(get_jwt_identity())
    subs = UserSubscription.query.filter_by(user_id=uid).order_by(
        UserSubscription.created_at.desc()
    ).limit(20).all()

    result = []
    for s in subs:
        config = EmailQuotaConfig.query.get(s.quota_config_id)
        # 试用期 = started_at + 7天
        trial_end = None
        if s.started_at:
            trial_end = s.started_at + timedelta(days=7)

        result.append({
            'id': s.id,
            'quota_config_id': s.quota_config_id,
            'payment_provider': s.payment_provider,
            'payment_order_id': s.payment_order_id,
            'amount_paid': s.amount_paid / 100 if s.amount_paid else 0,
            'plan_price': config.price_monthly / 100 if config and config.price_monthly else None,
            'plan_name': config.name if config else None,
            'trial_end': trial_end.isoformat() if trial_end else None,
            'trial_remaining_days': (trial_end - datetime.utcnow()).days if trial_end and trial_end > datetime.utcnow() else 0,
            'status': s.status,
            'started_at': s.started_at.isoformat() if s.started_at else None,
            'expires_at': s.expires_at.isoformat() if s.expires_at else None,
            'created_at': s.created_at.isoformat() if s.created_at else None,
        })

    return jsonify({'enabled': True, 'orders': result}), 200


@payment_bp.route('/my-subscription', methods=['GET'])
@jwt_required()
def get_my_subscription():
    """获取当前用户的有效订阅信息"""
    uid = int(get_jwt_identity())
    sub = UserSubscription.query.filter_by(user_id=uid, status='paid').order_by(
        UserSubscription.created_at.desc()
    ).first()

    if not sub:
        return jsonify({'active': False, 'plan': 'free'}), 200

    config = EmailQuotaConfig.query.get(sub.quota_config_id)
    return jsonify({
        'active': True,
        'plan': config.name if config else 'unknown',
        'daily_limit': config.daily_limit if config else 100,
        'provider': sub.payment_provider,
        'expires_at': sub.expires_at.isoformat() if sub.expires_at else None,
        'started_at': sub.started_at.isoformat() if sub.started_at else None,
    }), 200


def _get_plan_quota(quota_config_id):
    config = EmailQuotaConfig.query.get(quota_config_id)
    return config.daily_limit if config else 100


@payment_bp.route('/cancel-subscription', methods=['POST'])
@jwt_required()
def cancel_subscription():
    """用户主动取消订阅 (调用 Stripe API 取消自动续费)"""
    if not current_app.config.get('UPGRADE_FEATURE_ENABLED', False):
        return jsonify(msg='Payment not enabled'), 403

    uid = int(get_jwt_identity())
    data = request.get_json()
    subscription_id = data.get('subscription_id', '').strip()

    if not subscription_id:
        return jsonify(msg='subscription_id required'), 400

    # 验证订阅属于当前用户 (允许 paid 和 cancelling 状态)
    sub = UserSubscription.query.filter_by(
        user_id=uid,
        payment_order_id=subscription_id
    ).filter(UserSubscription.status.in_(['paid', 'cancelling'])).first()

    if not sub:
        return jsonify(msg='Active subscription not found'), 404

    try:
        stripe = _get_stripe()
        stripe_sub = stripe.Subscription.modify(
            subscription_id,
            cancel_at_period_end=True
        )
        # 更新本地状态为 cancelling
        sub.status = 'cancelling'
        if hasattr(stripe_sub, 'current_period_end') and stripe_sub.current_period_end:
            sub.expires_at = datetime.utcfromtimestamp(stripe_sub.current_period_end)
        db.session.commit()
        logger.info(f"[Stripe] Subscription marked for cancellation: {subscription_id} by user {uid}")
    except stripe_lib.error.StripeError as e:
        logger.error(f"[Stripe] Error cancelling subscription: {str(e)}")
        return jsonify(msg=f'Stripe error: {str(e)}'), 500

    # 通知用户
    notification = Notification(
        user_id=uid,
        type='subscription',
        title='Subscription Cancellation Scheduled',
        content='Your subscription will be cancelled at the end of the current billing period. You will be downgraded to the Free plan.',
    )
    db.session.add(notification)
    db.session.commit()

    return jsonify({
        'msg': 'Subscription will be cancelled at the end of the billing period',
        'status': 'cancelling',
        'expires_at': sub.expires_at.isoformat() if sub.expires_at else None
    }), 200


@payment_bp.route('/sync-subscriptions', methods=['POST'])
@jwt_required()
def sync_subscriptions():
    """
    从 Stripe 同步订阅记录到本地数据库
    用于服务端出错导致本地记录缺失时，从 Stripe 补齐
    """
    if not current_app.config.get('UPGRADE_FEATURE_ENABLED', False):
        return jsonify(msg='Payment not enabled'), 403

    uid = int(get_jwt_identity())
    stripe = _get_stripe()
    synced = 0

    try:
        # 从 Stripe 获取该用户的所有订阅（通过 email 匹配 customer）
        user = User.query.get(uid)
        if not user or not user.email:
            return jsonify(msg='User email not available'), 400

        customers = stripe.Customer.list(email=user.email, limit=5)
        customer_data = customers['data'] if 'data' in customers else []
        for customer in customer_data:
            subscriptions = stripe.Subscription.list(
                customer=customer['id'],
                limit=10,
                status='all'
            )
            sub_data = subscriptions['data'] if 'data' in subscriptions else []
            for stripe_sub in sub_data:
                sub_id = str(stripe_sub['id'])

                # 检查本地是否已有记录
                existing = UserSubscription.query.filter_by(
                    payment_order_id=sub_id
                ).first()
                if existing:
                    continue

                # 提取 metadata
                if 'metadata' in stripe_sub:
                    metadata_raw = stripe_sub['metadata']
                    metadata = json.loads(str(metadata_raw)) if str(metadata_raw) not in ('{}', 'None') else {}
                else:
                    metadata = {}

                quota_id = int(metadata.get('quota_config_id', 0))
                plan_name = metadata.get('plan', 'unknown')

                stripe_status = str(stripe_sub['status']) if 'status' in stripe_sub else ''
                mapping = {
                    'active': 'paid',
                    'trialing': 'paid',
                    'canceled': 'cancelled',
                    'incomplete': 'pending',
                    'incomplete_expired': 'expired',
                    'past_due': 'paid',
                    'unpaid': 'pending',
                }
                local_status = mapping.get(stripe_status, 'pending')

                # 从 items.data[0].price.unit_amount 提取金额
                amount = 0
                if 'items' in stripe_sub:
                    items_obj = stripe_sub['items']
                    item_data = items_obj['data'] if 'data' in items_obj else []
                    if item_data and len(item_data) > 0:
                        first_item = item_data[0]
                        price_obj = first_item['price'] if 'price' in first_item else {}
                        amount = price_obj.get('unit_amount', 0) if hasattr(price_obj, 'get') else 0

                created_ts = stripe_sub['created'] if 'created' in stripe_sub else 0
                period_end_ts = stripe_sub['current_period_end'] if 'current_period_end' in stripe_sub else 0

                sub = UserSubscription(
                    user_id=uid,
                    quota_config_id=quota_id,
                    payment_provider='stripe',
                    payment_order_id=sub_id,
                    amount_paid=amount,
                    status=local_status,
                    started_at=datetime.utcfromtimestamp(created_ts) if created_ts else datetime.utcnow(),
                    expires_at=datetime.utcfromtimestamp(period_end_ts) if period_end_ts else None,
                )
                db.session.add(sub)
                synced += 1

                # 如果不是免费的且本地状态为 paid，更新配额
                if local_status == 'paid' and quota_id:
                    _update_user_quota(uid, quota_id)

        db.session.commit()
        logger.info(f"[Stripe] Synced {synced} subscriptions for user {uid}")
        return jsonify({'msg': f'Synced {synced} subscription(s)', 'count': synced}), 200

    except Exception as e:
        logger.error(f"[Stripe] Sync failed for user {uid}: {repr(e)}", exc_info=True)
        db.session.rollback()
        return jsonify(msg=f'Sync failed: {str(e)}'), 500