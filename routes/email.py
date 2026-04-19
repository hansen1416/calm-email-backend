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
    print(f"\n{'='*60}")
    print(f"[MOCK] 模拟发送邮件:")
    print(f"  收件人: {to_email}")
    print(f"  主题: {subject}")
    print(f"  模拟MessageId: mock-{uuid.uuid4().hex[:16]}")
    print(f"  状态: 模拟成功 (mock_send=True)")
    print(f"{'='*60}")
    return True, f"mock-{uuid.uuid4().hex[:16]}"

def send_ses_email(to_email, subject, body_html):
    cfg = current_app.config
    print(f"\n{'='*60}")
    print(f"[SES] 准备发送邮件:")
    print(f"  收件人: {to_email}")
    print(f"  主题: {subject}")
    print(f"  发件人: {cfg['SES_SENDER_EMAIL']}")
    print(f"  AWS Region: {cfg['AWS_REGION']}")
    print(f"  AWS Key ID: {cfg['AWS_ACCESS_KEY_ID'][:8]}...")
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
        print(f"[SES] 发送失败!")
        print(f"  错误码: {e.response['Error']['Code']}")
        print(f"  错误信息: {e.response['Error']['Message']}")
        print(f"  完整异常: {traceback.format_exc()}")
        return False, None
    except Exception as e:
        print(f"[SES] 发送失败 (非AWS异常)!")
        print(f"  异常类型: {type(e).__name__}")
        print(f"  异常信息: {str(e)}")
        print(f"  完整异常: {traceback.format_exc()}")
        return False, None

def send_email(to_email, subject, body_html, mock=False):
    """
    统一邮件发送函数
    根据 mock 参数或全局配置决定发送方式
    
    Args:
        to_email: 收件人邮箱
        subject: 邮件主题
        body_html: 邮件正文HTML
        mock: True=强制模拟发送, False=使用全局配置
    
    Returns:
        (success: bool, message_id: str)
    """
    cfg = current_app.config
    
    # 判断是否使用模拟模式
    use_mock = mock or cfg.get('MOCK_EMAIL_SEND', False)
    
    if use_mock:
        return send_mock_email(to_email, subject, body_html)
    else:
        return send_ses_email(to_email, subject, body_html)

@email_bp.route('/send', methods=['POST'])
@jwt_required()
def send_email_api():
    uid = int(get_jwt_identity())
    data = request.get_json()
    template_id = data.get('template_id')
    contact_ids = data.get('contact_ids', [])
    group_ids = data.get('group_ids', [])
    mock = data.get('mock', False)  # 可选：强制模拟发送

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
                       subject=tpl.subject, status='sent' if ok else 'failed')
        db.session.add(log)
        results.append(dict(email=addr, status='sent' if ok else 'failed', message_id=msg_id))
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