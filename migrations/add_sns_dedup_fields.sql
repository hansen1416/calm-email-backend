-- 添加 SNS 去重和延迟监控字段
-- 执行方式: mysql -u root -p contact_mail < add_sns_dedup_fields.sql

-- 添加新字段到 email_event 表
ALTER TABLE email_event
ADD COLUMN sns_message_id VARCHAR(100) NULL COMMENT 'SNS 消息唯一ID，用于去重',
ADD COLUMN sns_received_at DATETIME NULL COMMENT 'SNS 消息接收时间，用于计算回调延迟',
ADD COLUMN sns_delay_seconds FLOAT NULL COMMENT 'SNS 回调延迟秒数';

-- 添加唯一索引（用于去重）
-- 注意：MySQL 允许多个 NULL 值，所以唯一索引可以正常工作
CREATE UNIQUE INDEX idx_emailevent_sns_message_id ON email_event(sns_message_id);

-- 添加普通索引用于查询
CREATE INDEX idx_emailevent_sns_received_at ON email_event(sns_received_at);

-- 验证字段添加成功
DESCRIBE email_event;
