-- 移除外键约束脚本
-- 执行前请备份数据库
-- 执行方式: mysql -u root -p contact_mail < remove_foreign_keys.sql

-- 关闭外键检查
SET FOREIGN_KEY_CHECKS = 0;

-- 1. contact 表
ALTER TABLE contact DROP FOREIGN KEY IF EXISTS contact_ibfk_1;

-- 2. contact_group 表
ALTER TABLE contact_group DROP FOREIGN KEY IF EXISTS contact_group_ibfk_1;

-- 3. email_template 表
ALTER TABLE email_template DROP FOREIGN KEY IF EXISTS email_template_ibfk_1;

-- 4. workflow 表
ALTER TABLE workflow DROP FOREIGN KEY IF EXISTS workflow_ibfk_1;

-- 5. workflow_instance 表
ALTER TABLE workflow_instance DROP FOREIGN KEY IF EXISTS workflow_instance_ibfk_1;
ALTER TABLE workflow_instance DROP FOREIGN KEY IF EXISTS workflow_instance_ibfk_2;

-- 6. email_log 表
ALTER TABLE email_log DROP FOREIGN KEY IF EXISTS email_log_ibfk_1;
ALTER TABLE email_log DROP FOREIGN KEY IF EXISTS email_log_ibfk_2;
ALTER TABLE email_log DROP FOREIGN KEY IF EXISTS email_log_ibfk_3;
ALTER TABLE email_log DROP FOREIGN KEY IF EXISTS email_log_ibfk_4;
ALTER TABLE email_log DROP FOREIGN KEY IF EXISTS email_log_ibfk_5;

-- 7. email_event 表
ALTER TABLE email_event DROP FOREIGN KEY IF EXISTS email_event_ibfk_1;
ALTER TABLE email_event DROP FOREIGN KEY IF EXISTS email_event_ibfk_2;
ALTER TABLE email_event DROP FOREIGN KEY IF EXISTS email_event_ibfk_3;

-- 8. node_execution 表
ALTER TABLE node_execution DROP FOREIGN KEY IF EXISTS node_execution_ibfk_1;
ALTER TABLE node_execution DROP FOREIGN KEY IF EXISTS node_execution_ibfk_2;

-- 9. group_contacts 表
ALTER TABLE group_contacts DROP FOREIGN KEY IF EXISTS group_contacts_ibfk_1;
ALTER TABLE group_contacts DROP FOREIGN KEY IF EXISTS group_contacts_ibfk_2;

-- 重新开启外键检查
SET FOREIGN_KEY_CHECKS = 1;

-- 验证外键是否已删除
SELECT 
    TABLE_NAME,
    CONSTRAINT_NAME,
    COLUMN_NAME,
    REFERENCED_TABLE_NAME,
    REFERENCED_COLUMN_NAME
FROM
    INFORMATION_SCHEMA.KEY_COLUMN_USAGE
WHERE
    TABLE_SCHEMA = DATABASE()
    AND REFERENCED_TABLE_NAME IS NOT NULL;
