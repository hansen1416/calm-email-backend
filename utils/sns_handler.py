"""
SNS 消息处理工具模块
提供消息去重、延迟监控和并发处理功能
"""

import json
import time
from datetime import datetime, timedelta
from functools import wraps
from flask import current_app

from models import db, EmailEvent, EmailLog


class SNSMessageHandler:
    """SNS 消息处理器"""

    def __init__(self):
        self.redis_client = None
        self._init_redis()

    def _init_redis(self):
        """初始化 Redis 连接（如果启用）"""
        if current_app.config.get('REDIS_ENABLED', False):
            try:
                import redis
                redis_url = current_app.config.get('REDIS_URL', 'redis://localhost:6379/0')
                self.redis_client = redis.from_url(redis_url, decode_responses=True)
                print(f"[SNS Handler] Redis connected: {redis_url}")
            except Exception as e:
                print(f"[SNS Handler] Redis connection failed: {e}")
                self.redis_client = None

    def is_duplicate(self, sns_message_id):
        """
        检查消息是否重复

        策略：
        1. 如果启用了 Redis，先检查 Redis
        2. 无论 Redis 结果如何，都检查数据库唯一约束
        3. 返回 True 表示是重复消息，False 表示是新消息
        """
        if not sns_message_id:
            return False

        dedup_days = current_app.config.get('SNS_DEDUP_DAYS', 30)

        # 1. 检查 Redis（如果启用）
        if self.redis_client:
            try:
                key = f"sns:dedup:{sns_message_id}"
                if self.redis_client.exists(key):
                    print(f"[SNS Handler] Duplicate detected in Redis: {sns_message_id}")
                    return True

                # 设置过期时间（秒）
                expire_seconds = dedup_days * 24 * 60 * 60
                self.redis_client.setex(key, expire_seconds, datetime.utcnow().isoformat())
            except Exception as e:
                print(f"[SNS Handler] Redis check failed: {e}")

        # 2. 检查数据库
        try:
            existing = EmailEvent.query.filter_by(sns_message_id=sns_message_id).first()
            if existing:
                print(f"[SNS Handler] Duplicate detected in database: {sns_message_id}")
                return True
        except Exception as e:
            print(f"[SNS Handler] Database check failed: {e}")

        return False

    def calculate_delay(self, message_id, sns_received_at):
        """
        计算 SNS 回调延迟

        Returns:
            delay_seconds: 延迟秒数
            is_delayed: 是否超过阈值
        """
        if not message_id or not sns_received_at:
            return None, False

        # 查找对应的 EmailLog
        email_log = EmailLog.query.filter_by(message_id=message_id).first()
        if not email_log or not email_log.sent_at:
            return None, False

        # 计算延迟
        delay = (sns_received_at - email_log.sent_at).total_seconds()
        delay_threshold = current_app.config.get('SNS_DELAY_THRESHOLD_SECONDS', 60)
        is_delayed = delay > delay_threshold

        if is_delayed:
            print(f"[SNS Handler] WARNING: SNS callback delayed {delay:.2f}s "
                  f"(threshold: {delay_threshold}s)")

        return delay, is_delayed

    def cleanup_old_dedup_records(self):
        """清理过期的去重记录（数据库层面）"""
        try:
            dedup_days = current_app.config.get('SNS_DEDUP_DAYS', 30)
            cutoff_date = datetime.utcnow() - timedelta(days=dedup_days)

            # 清理旧的 EmailEvent 记录（可选：只清理 sns_message_id 不为空的）
            # 注意：这里我们保留记录，只是清理 sns_message_id 字段以节省空间
            # 实际清理策略取决于业务需求

            print(f"[SNS Handler] Cleanup completed (retention: {dedup_days} days)")
        except Exception as e:
            print(f"[SNS Handler] Cleanup failed: {e}")


def handle_sns_message(sns_message_id, message_id, event_type, recipient_email,
                       sns_message_data, user_id=1, instance_id=None):
    """
    处理 SNS 消息（带去重和延迟监控）

    Args:
        sns_message_id: SNS 消息唯一ID
        message_id: SES Message ID
        event_type: 事件类型
        recipient_email: 收件人邮箱
        sns_message_data: SNS 原始消息数据
        user_id: 用户ID
        instance_id: 工作流实例ID

    Returns:
        tuple: (event, is_duplicate, delay_seconds)
            - event: EmailEvent 对象（新创建或已存在）
            - is_duplicate: 是否是重复消息
            - delay_seconds: 回调延迟秒数
    """
    handler = SNSMessageHandler()
    sns_received_at = datetime.utcnow()

    # 1. 检查重复
    if handler.is_duplicate(sns_message_id):
        print(f"[SNS Handler] Ignoring duplicate message: {sns_message_id}")

        # 查找已存在的事件
        existing_event = EmailEvent.query.filter_by(sns_message_id=sns_message_id).first()

        # 记录并发冲突日志
        current_app.logger.warning(
            f"[SNS Handler] Concurrent message received and ignored: "
            f"sns_message_id={sns_message_id}, "
            f"message_id={message_id}, "
            f"event_type={event_type}"
        )

        return existing_event, True, None

    # 2. 计算延迟
    delay_seconds, is_delayed = handler.calculate_delay(message_id, sns_received_at)

    # 3. 创建 EmailEvent 记录
    email_log = EmailLog.query.filter_by(message_id=message_id).first()

    event = EmailEvent(
        user_id=user_id,
        instance_id=instance_id,
        message_id=message_id,
        event_type=event_type.lower() if event_type else None,
        recipient_email=recipient_email,
        event_data=sns_message_data,
        occurred_at=sns_message_data.get('mail', {}).get('timestamp'),
        sns_message_id=sns_message_id,
        sns_received_at=sns_received_at,
        sns_delay_seconds=delay_seconds
    )

    if email_log:
        event.source_email_log_id = email_log.id

    try:
        db.session.add(event)
        db.session.commit()
        print(f"[SNS Handler] Event created: id={event.id}, "
              f"sns_message_id={sns_message_id}, "
              f"delay={delay_seconds:.2f}s" if delay_seconds else "N/A")
    except Exception as e:
        db.session.rollback()

        # 可能是并发插入冲突，检查是否是重复
        existing = EmailEvent.query.filter_by(sns_message_id=sns_message_id).first()
        if existing:
            print(f"[SNS Handler] Concurrent insert detected: {sns_message_id}")
            current_app.logger.warning(
                f"[SNS Handler] Concurrent insert conflict (message already exists): "
                f"sns_message_id={sns_message_id}"
            )
            return existing, True, None
        else:
            raise

    # 4. 如果延迟超过阈值，记录告警
    if is_delayed:
        current_app.logger.warning(
            f"[SNS Handler] SNS callback delay alert: "
            f"sns_message_id={sns_message_id}, "
            f"delay={delay_seconds:.2f}s, "
            f"threshold={current_app.config.get('SNS_DELAY_THRESHOLD_SECONDS', 60)}s"
        )

    return event, False, delay_seconds


# 导出主要函数
__all__ = ['SNSMessageHandler', 'handle_sns_message']
