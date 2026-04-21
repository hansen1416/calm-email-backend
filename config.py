
import os
import secrets
from datetime import timedelta
from dotenv import load_dotenv

# 加载 .env 文件（如果存在）
# 从当前工作目录向上查找 .env 文件
load_dotenv(override=True)

class Config:
    # 安全密钥配置
    # 生产环境必须通过环境变量设置，否则每次重启会生成新密钥
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        # 开发环境：生成临时密钥（每次重启会失效旧 token）
        SECRET_KEY = secrets.token_hex(32)
        print(f"[WARNING] Using temporary SECRET_KEY. Set SECRET_KEY env var for production.")
    
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY')
    if not JWT_SECRET_KEY:
        JWT_SECRET_KEY = secrets.token_hex(32)
        print(f"[WARNING] Using temporary JWT_SECRET_KEY. Set JWT_SECRET_KEY env var for production.")
    
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=24)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)  # 刷新令牌30天过期
    
    # 数据库配置
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URI',
        'mysql+pymysql://root:root@192.168.56.131:3306/contact_mail'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # SQLAlchemy 连接池配置 - 防止 "Lost connection to MySQL server" 错误
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,        # 使用前 ping 检查连接是否有效
        'pool_recycle': 3600,         # 1小时后回收连接（避免 MySQL wait_timeout）
        'pool_size': 10,              # 基础连接池大小
        'max_overflow': 20,           # 最大溢出连接数
        'pool_timeout': 30,           # 获取连接超时时间（秒）
        'connect_args': {
            'connect_timeout': 10,    # 连接超时（秒）
        }
    }

    # AWS SES 配置
    # ⚠️ 生产环境必须通过环境变量设置，不要硬编码凭证
    AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')
    
    AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
    SES_SENDER_EMAIL = os.environ.get('SES_SENDER_EMAIL', 'noreply@example.com')
    
    # 检查 AWS 凭证配置
    if not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY:
        print(f"[WARNING] AWS credentials not set. Email sending will fail in production mode.")
        print(f"          Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables.")

    # 模拟发送模式（开发/测试用）
    MOCK_EMAIL_SEND = os.environ.get('MOCK_EMAIL_SEND', 'true').lower() in ('true', '1', 'yes')
    
    # CORS 配置 - 生产环境应限制域名
    CORS_ORIGINS = os.environ.get('CORS_ORIGINS', '*')
    
    # 日志级别
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
    
    # 请求限流配置（需要安装 Flask-Limiter）
    # RATELIMIT_STORAGE_URI = os.environ.get('RATELIMIT_STORAGE_URI', 'memory://')
    
    # CSRF 配置
    WTF_CSRF_ENABLED = os.environ.get('WTF_CSRF_ENABLED', 'false').lower() == 'true'
    WTF_CSRF_SECRET_KEY = os.environ.get('WTF_CSRF_SECRET_KEY')

    # SNS 回调配置
    # 消息去重：保存已处理消息ID的天数
    SNS_DEDUP_DAYS = int(os.environ.get('SNS_DEDUP_DAYS', '30'))

    # 回调延迟告警阈值（秒）
    SNS_DELAY_THRESHOLD_SECONDS = int(os.environ.get('SNS_DELAY_THRESHOLD_SECONDS', '60'))

    # Redis 配置（用于消息去重，可选）
    REDIS_ENABLED = os.environ.get('REDIS_ENABLED', 'false').lower() in ('true', '1', 'yes')
    REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
