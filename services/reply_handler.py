"""
邮件回复处理服务
M5: 转发回复到用户真实邮箱 + 系统通知

说明:
- 当前实现为预留接口，支持两种方案
- 方案A: SES Inbound Email + Lambda (AWS原生)
- 方案B: 第三方转发服务 (如 ForwardMX, ImprovMX)
"""

import boto3
from flask import current_app
from botocore.exceptions import ClientError
from models import db, UserSenderBinding, Notification
import re


def extract_system_email_from_recipient(recipient_email):
    """
    从收件地址提取系统邮箱
    例如: user001@mail.yourdomain.com -> user001@mail.yourdomain.com
    """
    if not recipient_email:
        return None
    
    # 清理地址
    email = recipient_email.strip().lower()
    
    # 检查是否匹配系统域名
    system_domain = current_app.config.get('SYSTEM_DOMAIN', '')
    if system_domain and email.endswith(f'@{system_domain}'):
        return email
    
    return None


def get_binding_by_system_email(system_email):
    """
    根据系统邮箱查找用户绑定
    Returns: UserSenderBinding or None
    """
    if not system_email:
        return None
    
    binding = UserSenderBinding.query.filter_by(
        email=system_email,
        email_type='system',
        is_active=True
    ).first()
    
    return binding


def forward_reply_to_user(system_email, original_recipient, subject, body, attachments=None):
    """
    转发回复邮件到用户真实邮箱
    
    Args:
        system_email: 系统子邮箱 (如 user001@mail.yourdomain.com)
        original_recipient: 原始收件人 (Reply-To中的地址)
        subject: 邮件主题
        body: 邮件正文
        attachments: 附件列表 (预留)
    
    Returns:
        bool: 是否成功
    """
    # 查找绑定
    binding = get_binding_by_system_email(system_email)
    if not binding:
        current_app.logger.warning(f"[Reply] No binding found for {system_email}")
        return False
    
    if not binding.real_email:
        current_app.logger.warning(f"[Reply] No real_email set for {system_email}")
        return False
    
    try:
        # 构建转发邮件
        forward_subject = f"[Re: {subject[:50]}...]" if len(subject) > 50 else f"[Re: {subject}]"
        forward_body = f"""
<html>
<body>
<p><strong>您收到了新的邮件回复</strong></p>
<hr/>
<p><strong>原邮件:</strong> {subject}</p>
<p><strong>发件人:</strong> {original_recipient}</p>
<p><strong>时间:</strong> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}</p>
<hr/>
<p><strong>回复内容:</strong></p>
<div style="border-left: 3px solid #ccc; padding-left: 10px; margin: 10px 0;">
{body}
</div>
<hr/>
<p style="color: #666; font-size: 12px;">
此邮件由 MailFlow 系统自动转发<br/>
您的系统邮箱: {system_email}
</p>
</body>
</html>
"""
        
        # 发送转发邮件
        client = boto3.client(
            'ses',
            region_name=current_app.config['AWS_REGION'],
            aws_access_key_id=current_app.config['AWS_ACCESS_KEY_ID'],
            aws_secret_access_key=current_app.config['AWS_SECRET_ACCESS_KEY']
        )
        
        response = client.send_email(
            Source=current_app.config.get('SES_DEFAULT_SENDER', 'noreply@example.com'),
            Destination={'ToAddresses': [binding.real_email]},
            Message={
                'Subject': {'Data': forward_subject, 'Charset': 'UTF-8'},
                'Body': {'Html': {'Data': forward_body, 'Charset': 'UTF-8'}}
            }
        )
        
        current_app.logger.info(f"[Reply] Forwarded to {binding.real_email}")
        return True
        
    except ClientError as e:
        current_app.logger.error(f"[Reply] Forward failed: {e}")
        return False
    except Exception as e:
        current_app.logger.error(f"[Reply] Unexpected error: {e}")
        return False


def create_reply_notification(binding, subject, preview):
    """
    创建系统内通知
    
    Args:
        binding: UserSenderBinding
        subject: 邮件主题
        preview: 内容预览
    """
    try:
        notification = Notification(
            user_id=binding.user_id,
            type='email_reply',
            title=f'收到邮件回复: {subject[:50]}{"..." if len(subject) > 50 else ""}',
            content=preview[:500],  # 限制长度
            related_data={
                'system_email': binding.email,
                'real_email': binding.real_email,
                'subject': subject
            }
        )
        db.session.add(notification)
        db.session.commit()
        
        current_app.logger.info(f"[Reply] Notification created for user {binding.user_id}")
        return True
        
    except Exception as e:
        current_app.logger.error(f"[Reply] Notification creation failed: {e}")
        db.session.rollback()
        return False


def process_inbound_reply(recipient, sender, subject, body):
    """
    处理入站回复邮件 (预留接口)
    
    调用方式:
    1. SES Inbound Email -> SNS -> Lambda -> 调用此API
    2. 第三方服务 webhook -> 调用此API
    
    Args:
        recipient: 收件人地址 (系统子邮箱)
        sender: 发送者地址
        subject: 邮件主题
        body: 邮件正文
    
    Returns:
        dict: 处理结果
    """
    # 提取系统邮箱
    system_email = extract_system_email_from_recipient(recipient)
    if not system_email:
        return {'success': False, 'error': 'Not a system email'}
    
    # 查找绑定
    binding = get_binding_by_system_email(system_email)
    if not binding:
        return {'success': False, 'error': 'Binding not found'}
    
    if not binding.real_email:
        return {'success': False, 'error': 'No real_email configured'}
    
    # 1. 转发到真实邮箱
    forward_ok = forward_reply_to_user(
        system_email=system_email,
        original_recipient=sender,
        subject=subject,
        body=body
    )
    
    # 2. 创建系统通知
    preview = body[:200] + '...' if len(body) > 200 else body
    notify_ok = create_reply_notification(binding, subject, preview)
    
    return {
        'success': forward_ok and notify_ok,
        'forwarded': forward_ok,
        'notified': notify_ok,
        'system_email': system_email,
        'real_email': binding.real_email
    }


# ==========================================
# SES Inbound Email 配置指南 (预留文档)
# ==========================================
"""
方案A: SES Inbound Email 配置步骤

1. 验证接收域名
   - SES Console > Configuration > Verified identities
   - 添加 mail.yourdomain.com
   - 验证域名所有权

2. 创建接收规则集
   - SES Console > Configuration > Email receiving > Rule sets
   - 创建新规则集 (Active)

3. 创建接收规则
   - Recipient: user*@mail.yourdomain.com (匹配所有子邮箱)
   - Actions:
     a. S3: 保存邮件到 S3 bucket
     b. Lambda: 触发处理函数
     c. SNS: 可选，用于通知

4. Lambda 函数示例 (Python)
   ```python
   import json
   import boto3
   import requests
   
   def lambda_handler(event, context):
       # 从 S3 获取邮件内容
       s3 = boto3.client('s3')
       bucket = event['Records'][0]['s3']['bucket']['name']
       key = event['Records'][0]['s3']['object']['key']
       
       response = s3.get_object(Bucket=bucket, Key=key)
       email_content = response['Body'].read().decode('utf-8')
       
       # 解析邮件
       # ... 使用 email.parser 解析 ...
       
       # 调用后端 API
       api_url = 'https://your-api.com/api/webhooks/inbound-reply'
       requests.post(api_url, json={
           'recipient': parsed_email['to'],
           'sender': parsed_email['from'],
           'subject': parsed_email['subject'],
           'body': parsed_email['body']
       })
   ```

方案B: 第三方服务

1. ForwardMX / ImprovMX
   - 注册并添加域名 mail.yourdomain.com
   - 配置 MX 记录指向服务
   - 设置 webhook URL: https://your-api.com/api/webhooks/inbound-reply
   - 所有回复自动转发到 webhook

2. 后端接收 webhook
   - 实现 /api/webhooks/inbound-reply 端点
   - 调用 process_inbound_reply() 处理
"""

from datetime import datetime
