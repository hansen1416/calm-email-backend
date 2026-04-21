import traceback
import uuid
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, EmailTemplate, EmailLog, Contact, ContactGroup
import boto3
from botocore.exceptions import ClientError

email_bp = Blueprint('email', __name__)


def send_mock_email(to_email, subject, body_html):
    """模拟邮件发送，仅记录日志不真实发送"""
    msg_id = f"mock-{uuid.uuid4().hex[:16]}"
    print(f"\n{'='*60}")
    print(f"[MOCK] 模拟发送邮件:")
    print(f" 收件人: {to_email}")
    print(f" 主题: {subject}")
    print(f" 模拟MessageId: {msg_id}")
    print(f" 状态: 模拟成功 (mock_send=True)")
    print(f"{'='*60}")
    return True, msg_id


def send_ses_email(to_email, subject, body_html):
    """使用 AWS SES 发送邮件，包含详细的错误处理"""
    cfg = current_app.config
    print(f"\n{'='*60}")
    print(f"[SES] 准备发送邮件:")
    print(f" 收件人: {to_email}")
    print(f" 主题: {subject}")
    print(f" 发件人: {cfg['SES_SENDER_EMAIL']}")
    print(f" AWS Region: {cfg['AWS_REGION']}")
    print(f" AWS Key ID: {cfg['AWS_ACCESS_KEY_ID'][:8]}...")
    print(f"{'='*60}")

    client = boto3.client(
        'ses', region_name=cfg['AWS_REGION'],
        aws_access_key_id=cfg['AWS_ACCESS_KEY_ID'],
        aws_secret_access_key=cfg['AWS_SECRET_ACCESS_KEY']
    )
    try:
        response = client.send_email(
            Source=cfg['SES_SENDER_EMAIL'],
            Destination={'ToAddresses': [to_email]},
            Message={
                'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                'Body': {'Html': {'Data': body_html, 'Charset': 'UTF-8'}}
            }
        )
        print(f"[SES] 发送成功! MessageId: {response.get('MessageId')}")
        return True, response.get('MessageId')
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        print(f"[SES] 发送失败!")
        print(f" 错误码: {error_code}")
        print(f" 错误信息: {error_message}")

        # 提供友好的错误提示
        user_message = get_ses_error_message(error_code, error_message, to_email)
        print(f" 用户提示: {user_message}")
        print(f" 完整异常: {traceback.format_exc()}")

        return False, f"{error_code}: {user_message}"
    except Exception as e:
        print(f"[SES] 发送失败 (非AWS异常)!")
        print(f" 异常类型: {type(e).__name__}")
        print(f" 异常信息: {str(e)}")
        print(f" 完整异常: {traceback.format_exc()}")
        return False, f"UNKNOWN: {str(e)}"


def get_ses_error_message(error_code, error_message, recipient_email):
    """
    将 SES 错误码转换为友好的中文提示信息
    """
    error_messages = {
        'MessageRejected': {
            'pattern': 'Email address is not verified',
            'title': '邮箱未验证',
            'solutions': [
                '原因1: SES 处于沙盒模式，收件人邮箱需要先验证',
                '原因2: 发件人邮箱 (SES_SENDER_EMAIL) 未在 SES 控制台验证',
                '解决方案:',
                '  1. 登录 AWS SES 控制台',
                '  2. 验证发件人邮箱身份',
                '  3. 在 SES > Configuration > Verified identities 中添加并验证邮箱',
                '  4. 申请生产访问权限 (Production access) 以解除沙盒限制'
            ]
        },
        'MailFromDomainNotVerified': {
            'title': '发件域未验证',
            'solutions': [
                '原因: 发件人邮箱的域名未在 SES 中验证',
                '解决方案: 在 SES 控制台验证整个域名或验证特定邮箱地址'
            ]
        },
        'ConfigurationSetDoesNotExist': {
            'title': '配置集不存在',
            'solutions': [
                '原因: 指定的 ConfigurationSet 不存在',
                '解决方案: 在 SES 控制台创建配置集或在代码中移除 ConfigurationSet 参数'
            ]
        },
        'TemplateDoesNotExist': {
            'title': 'SES 模板不存在',
            'solutions': [
                '原因: 使用的 SES 模板名称不存在',
                '解决方案: 在 SES 控制台创建模板或检查模板名称是否正确'
            ]
        },
        'LimitExceeded': {
            'title': '超出发送限制',
            'solutions': [
                '原因: 超出 SES 发送配额或速率限制',
                '解决方案:',
                '  1. 检查 SES > Sending statistics 查看当前配额',
                '  2. 申请提高发送配额',
                '  3. 降低发送速率'
            ]
        },
        'AccountSendingPaused': {
            'title': '账户发送暂停',
            'solutions': [
                '原因: AWS 因高退信率或投诉率暂停了您的发送权限',
                '解决方案: 联系 AWS Support 恢复发送权限'
            ]
        }
    }

    # 匹配错误码
    if error_code in error_messages:
        info = error_messages[error_code]
        # 检查是否有特定的模式匹配
        if 'pattern' in info and info['pattern'] in error_message:
            return f"{info['title']}\n" + "\n".join(info['solutions'])
        elif 'pattern' not in info:
            return f"{info['title']}\n" + "\n".join(info['solutions'])

    # 默认错误信息
    return f"SES 错误: {error_message}\n建议: 请检查 AWS SES 配置和邮箱验证状态"


def send_email(to_email, subject, body_html, mock=False):
    """
    统一邮件发送函数
    根据 mock 参数或全局配置决定发送方式
    """
    cfg = current_app.config
    use_mock = mock or cfg.get('MOCK_EMAIL_SEND', False)

    if use_mock:
        return send_mock_email(to_email, subject, body_html)
    else:
        return send_ses_email(to_email, subject, body_html)


@email_bp.route('/send', methods=['POST'])
@jwt_required()
def send_email_api():
    """发送邮件 API"""
    uid = int(get_jwt_identity())
    data = request.get_json()
    template_id = data.get('template_id')
    contact_ids = data.get('contact_ids', [])
    group_ids = data.get('group_ids', [])
    mock = data.get('mock', False)

    if not template_id:
        return jsonify(msg='请选择邮件模板'), 400

    tpl = EmailTemplate.query.filter_by(id=template_id, user_id=uid).first()
    if not tpl:
        return jsonify(msg='模板不存在'), 404

    emails = set()
    if contact_ids:
        contacts = Contact.query.filter(Contact.id.in_(contact_ids), Contact.user_id == uid).all()
        for c in contacts:
            emails.add(c.email)
    if group_ids:
        groups = ContactGroup.query.filter(ContactGroup.id.in_(group_ids), ContactGroup.user_id == uid).all()
        for g in groups:
            for c in g.contacts:
                emails.add(c.email)

    if not emails:
        return jsonify(msg='没有收件人'), 400

    results = []
    for addr in emails:
        ok, msg_id = send_email(addr, tpl.subject, tpl.body, mock=mock)
        log = EmailLog(user_id=uid, template_id=tpl.id, recipient_email=addr,
                       subject=tpl.subject, status='sent' if ok else 'failed',
                       message_id=msg_id if ok else None)
        db.session.add(log)
        results.append({
            'email': addr,
            'status': 'sent' if ok else 'failed',
            'message_id': msg_id if ok else None,
            'error': None if ok else msg_id  # 失败时 msg_id 存储错误信息
        })
    db.session.commit()
    return jsonify(results=results), 200


@email_bp.route('/settings', methods=['GET'])
@jwt_required()
def get_email_settings():
    """获取邮件发送设置"""
    cfg = current_app.config
    return jsonify({
        'mock_mode': cfg.get('MOCK_EMAIL_SEND', False),
        'sender_email': cfg.get('SES_SENDER_EMAIL'),
        'aws_region': cfg.get('AWS_REGION')
    }), 200


@email_bp.route('/ses-status', methods=['GET'])
@jwt_required()
def get_ses_status():
    """
    获取 SES 身份验证状态和发送配额
    """
    cfg = current_app.config

    # 检查 AWS 凭证是否配置
    if not cfg.get('AWS_ACCESS_KEY_ID') or not cfg.get('AWS_SECRET_ACCESS_KEY'):
        return jsonify({
            'configured': False,
            'error': 'AWS 凭证未配置',
            'solutions': [
                '设置 AWS_ACCESS_KEY_ID 环境变量',
                '设置 AWS_SECRET_ACCESS_KEY 环境变量'
            ]
        }), 200

    try:
        client = boto3.client(
            'ses', region_name=cfg['AWS_REGION'],
            aws_access_key_id=cfg['AWS_ACCESS_KEY_ID'],
            aws_secret_access_key=cfg['AWS_SECRET_ACCESS_KEY']
        )

        # 获取发送配额
        quota = client.get_send_quota()

        # 获取已验证的邮箱地址列表
        verified_identities = client.list_identities(IdentityType='EmailAddress')
        verified_domains = client.list_identities(IdentityType='Domain')

        # 获取 SES 统计信息（用于判断是否在生产环境）
        try:
            stats = client.get_send_statistics()
            has_production_access = True  # 如果能获取统计，说明有生产权限
        except ClientError as e:
            has_production_access = False

        return jsonify({
            'configured': True,
            'region': cfg['AWS_REGION'],
            'sender_email': cfg.get('SES_SENDER_EMAIL'),
            'quota': {
                'max_24_hour_send': quota['Max24HourSend'],
                'max_send_rate': quota['MaxSendRate'],
                'sent_last_24_hours': quota['SentLast24Hours'],
                'remaining': quota['Max24HourSend'] - quota['SentLast24Hours']
            },
            'verified_emails': verified_identities['Identities'],
            'verified_domains': verified_domains['Identities'],
            'sender_email_verified': cfg.get('SES_SENDER_EMAIL') in verified_identities['Identities'],
            'has_production_access': has_production_access,
            'sandbox_mode': not has_production_access,
            'tips': generate_ses_tips(
                cfg.get('SES_SENDER_EMAIL'),
                verified_identities['Identities'],
                has_production_access
            )
        }), 200

    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        return jsonify({
            'configured': True,
            'error': f'{error_code}: {error_message}',
            'solutions': [
                '检查 AWS 凭证是否正确',
                '确认 IAM 用户具有 SES 访问权限 (ses:SendEmail, ses:GetSendQuota)',
                '检查 AWS Region 是否正确'
            ]
        }), 200
    except Exception as e:
        return jsonify({
            'configured': True,
            'error': str(e),
            'solutions': ['检查网络连接', '确认 AWS SES 服务可用']
        }), 200


def generate_ses_tips(sender_email, verified_emails, has_production_access):
    """生成 SES 配置建议"""
    tips = []

    if not sender_email:
        tips.append('警告: SES_SENDER_EMAIL 未配置')
    elif sender_email not in verified_emails:
        tips.append(f'警告: 发件人邮箱 {sender_email} 未在 SES 中验证')
        tips.append('请在 AWS SES 控制台验证该邮箱地址')

    if not has_production_access:
        tips.append('当前处于沙盒模式，只能发送给已验证的邮箱')
        tips.append('请申请 SES Production Access 以解除限制')

    if not tips:
        tips.append('SES 配置正常，可以发送邮件')

    return tips


@email_bp.route('/verify-email', methods=['POST'])
@jwt_required()
def request_verify_email():
    """
    请求验证邮箱地址（发送验证邮件）
    """
    cfg = current_app.config
    data = request.get_json()
    email = data.get('email')

    if not email:
        return jsonify(msg='请提供邮箱地址'), 400

    if not cfg.get('AWS_ACCESS_KEY_ID'):
        return jsonify(msg='AWS 凭证未配置'), 500

    try:
        client = boto3.client(
            'ses', region_name=cfg['AWS_REGION'],
            aws_access_key_id=cfg['AWS_ACCESS_KEY_ID'],
            aws_secret_access_key=cfg['AWS_SECRET_ACCESS_KEY']
        )

        # 发送验证请求
        response = client.verify_email_identity(EmailAddress=email)

        return jsonify({
            'msg': '验证邮件已发送',
            'email': email,
            'instruction': '请查收邮件并点击验证链接'
        }), 200

    except ClientError as e:
        return jsonify(
            msg=f"验证请求失败: {e.response['Error']['Message']}"
        ), 500


@email_bp.route('/send-template', methods=['POST'])
@jwt_required()
def send_template_email():
    """
    使用 SES 模板发送邮件
    需要先通过 AWS 控制台或 API 创建 SES 模板
    """
    cfg = current_app.config
    uid = int(get_jwt_identity())
    data = request.get_json()

    template_name = data.get('template_name')  # SES 模板名称
    contact_ids = data.get('contact_ids', [])
    group_ids = data.get('group_ids', [])
    template_data = data.get('template_data', {})  # 模板变量

    if not template_name:
        return jsonify(msg='请提供 SES 模板名称'), 400

    # 收集收件人
    emails = set()
    if contact_ids:
        contacts = Contact.query.filter(Contact.id.in_(contact_ids), Contact.user_id == uid).all()
        for c in contacts:
            emails.add(c.email)
    if group_ids:
        groups = ContactGroup.query.filter(ContactGroup.id.in_(group_ids), ContactGroup.user_id == uid).all()
        for g in groups:
            for c in g.contacts:
                emails.add(c.email)

    if not emails:
        return jsonify(msg='没有收件人'), 400

    if cfg.get('MOCK_EMAIL_SEND', False):
        # 模拟模式
        results = []
        for addr in emails:
            msg_id = f"mock-template-{uuid.uuid4().hex[:16]}"
            print(f"[MOCK TEMPLATE] To: {addr}, Template: {template_name}")
            log = EmailLog(user_id=uid, recipient_email=addr,
                           subject=f"[Template: {template_name}]", status='sent',
                           message_id=msg_id)
            db.session.add(log)
            results.append({'email': addr, 'status': 'sent', 'message_id': msg_id})
        db.session.commit()
        return jsonify(results=results), 200

    # SES 模板发送
    try:
        client = boto3.client(
            'ses', region_name=cfg['AWS_REGION'],
            aws_access_key_id=cfg['AWS_ACCESS_KEY_ID'],
            aws_secret_access_key=cfg['AWS_SECRET_ACCESS_KEY']
        )

        results = []
        for addr in emails:
            try:
                response = client.send_templated_email(
                    Source=cfg['SES_SENDER_EMAIL'],
                    Destination={'ToAddresses': [addr]},
                    Template=template_name,
                    TemplateData=json.dumps(template_data)
                )
                msg_id = response['MessageId']
                log = EmailLog(user_id=uid, recipient_email=addr,
                               subject=f"[Template: {template_name}]", status='sent',
                               message_id=msg_id)
                db.session.add(log)
                results.append({'email': addr, 'status': 'sent', 'message_id': msg_id})
            except ClientError as e:
                error_msg = get_ses_error_message(
                    e.response['Error']['Code'],
                    e.response['Error']['Message'],
                    addr
                )
                log = EmailLog(user_id=uid, recipient_email=addr,
                               subject=f"[Template: {template_name}]", status='failed')
                db.session.add(log)
                results.append({'email': addr, 'status': 'failed', 'error': error_msg})

        db.session.commit()
        return jsonify(results=results), 200

    except Exception as e:
        return jsonify(msg=f'发送失败: {str(e)}'), 500


@email_bp.route('/templates', methods=['GET'])
@jwt_required()
def list_ses_templates():
    """
    获取 SES 模板列表
    """
    cfg = current_app.config

    if cfg.get('MOCK_EMAIL_SEND', False):
        return jsonify({
            'templates': [
                {'name': 'WelcomeTemplate', 'created': '2024-01-01'},
                {'name': 'PromotionTemplate', 'created': '2024-01-01'}
            ],
            'mock_mode': True
        }), 200

    try:
        client = boto3.client(
            'ses', region_name=cfg['AWS_REGION'],
            aws_access_key_id=cfg['AWS_ACCESS_KEY_ID'],
            aws_secret_access_key=cfg['AWS_SECRET_ACCESS_KEY']
        )

        response = client.list_templates()
        templates = response.get('TemplatesMetadata', [])

        return jsonify({
            'templates': [
                {
                    'name': t['Name'],
                    'created': t['CreatedTimestamp'].isoformat() if 'CreatedTimestamp' in t else None
                }
                for t in templates
            ]
        }), 200

    except ClientError as e:
        return jsonify(msg=f"获取模板失败: {e.response['Error']['Message']}"), 500
