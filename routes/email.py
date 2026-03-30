import traceback
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, EmailTemplate, EmailLog, Contact, ContactGroup
import boto3
from botocore.exceptions import ClientError

email_bp = Blueprint('email', __name__)

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
        return True
    except ClientError as e:
        print(f"[SES] 发送失败!")
        print(f"  错误码: {e.response['Error']['Code']}")
        print(f"  错误信息: {e.response['Error']['Message']}")
        print(f"  完整异常: {traceback.format_exc()}")
        return False
    except Exception as e:
        print(f"[SES] 发送失败 (非AWS异常)!")
        print(f"  异常类型: {type(e).__name__}")
        print(f"  异常信息: {str(e)}")
        print(f"  完整异常: {traceback.format_exc()}")
        return False

@email_bp.route('/send', methods=['POST'])
@jwt_required()
def send_email():
    uid = int(get_jwt_identity())
    data = request.get_json()
    template_id = data.get('template_id')
    contact_ids = data.get('contact_ids', [])
    group_ids = data.get('group_ids', [])

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
        ok = send_ses_email(addr, tpl.subject, tpl.body)
        log = EmailLog(user_id=uid, template_id=tpl.id, recipient_email=addr,
                       subject=tpl.subject, status='sent' if ok else 'failed')
        db.session.add(log)
        results.append(dict(email=addr, status='sent' if ok else 'failed'))
    db.session.commit()
    return jsonify(results=results), 200
