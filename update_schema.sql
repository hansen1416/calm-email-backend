-- WorkflowInstance 表结构更新脚本
-- 执行时间: 2026-04-19

-- 创建 WorkflowInstance 表
CREATE TABLE IF NOT EXISTS workflow_instance (
    id INT AUTO_INCREMENT PRIMARY KEY,
    workflow_id INT NOT NULL,
    user_id INT NOT NULL,
    recipient_email VARCHAR(120) NOT NULL,
    message_id VARCHAR(100),
    status VARCHAR(20) DEFAULT 'pending',
    current_node_id VARCHAR(50),
    waiting_event_type VARCHAR(20),
    waiting_conditions JSON,
    waiting_since DATETIME,
    context JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    completed_at DATETIME,
    FOREIGN KEY (workflow_id) REFERENCES workflow(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE,
    INDEX idx_workflow_id (workflow_id),
    INDEX idx_user_id (user_id),
    INDEX idx_message_id (message_id),
    INDEX idx_status (status),
    INDEX idx_recipient_email (recipient_email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 修改 EmailLog 表，添加 instance_id 字段
ALTER TABLE email_log 
ADD COLUMN instance_id INT AFTER workflow_id,
ADD FOREIGN KEY (instance_id) REFERENCES workflow_instance(id) ON DELETE SET NULL,
ADD INDEX idx_instance_id (instance_id);

-- 修改 EmailEvent 表，添加 instance_id 字段
ALTER TABLE email_event 
ADD COLUMN instance_id INT AFTER user_id,
ADD FOREIGN KEY (instance_id) REFERENCES workflow_instance(id) ON DELETE SET NULL,
ADD INDEX idx_instance_id (instance_id);

-- 为 Workflow 表添加实例关系（可选，用于级联删除）
-- 已在 SQLAlchemy 中配置 cascade

-- 创建 NodeExecution 表（节点执行历史）
CREATE TABLE IF NOT EXISTS node_execution (
    id INT AUTO_INCREMENT PRIMARY KEY,
    instance_id INT NOT NULL,
    node_id VARCHAR(50) NOT NULL,
    node_type VARCHAR(20) NOT NULL,
    node_label VARCHAR(100),
    result VARCHAR(20) NOT NULL, -- success/waiting/resumed/failed/skipped
    input_data JSON,
    output_data JSON,
    resumed_by_event_id INT,
    event_data JSON,
    conditions_met BOOLEAN,
    error_message TEXT,
    executed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME,
    duration_ms INT,
    FOREIGN KEY (instance_id) REFERENCES workflow_instance(id) ON DELETE CASCADE,
    FOREIGN KEY (resumed_by_event_id) REFERENCES email_event(id) ON DELETE SET NULL,
    INDEX idx_instance_id (instance_id),
    INDEX idx_node_id (node_id),
    INDEX idx_result (result),
    INDEX idx_executed_at (executed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- APScheduler 任务存储表（用于延时任务持久化）
CREATE TABLE IF NOT EXISTS apscheduler_jobs (
    id VARCHAR(191) NOT NULL PRIMARY KEY,
    next_run_time DOUBLE PRECISION,
    job_state BLOB NOT NULL,
    INDEX idx_next_run_time (next_run_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ============================================================================
-- 数据库迁移脚本使用说明
-- ============================================================================
--
-- 执行方式：
--   方式1: 通过 MySQL 命令行直接执行
--     mysql -u root -p contact_mail < update_schema.sql
--
--   方式2: 通过 SSH 登录服务器后执行
--     ssh user@server "mysql -u root -p contact_mail" < update_schema.sql
--
--   方式3: 在 MySQL 客户端中执行
--     source /path/to/update_schema.sql;
--
-- 前置条件：
--   1. 确保数据库 contact_mail 已存在
--   2. 确保已备份数据库（建议执行前备份）
--      mysqldump -u root -p contact_mail > backup_$(date +%Y%m%d).sql
--   3. 确保有足够的权限创建表和修改表结构
--
-- 注意事项：
--   1. 此脚本使用 IF NOT EXISTS，可重复执行
--   2. 旧数据将保留，新执行的工作流将使用新架构
--   3. APScheduler 表用于延时任务持久化，服务重启后任务不会丢失
--
-- ============================================================================

-- 初始化说明
-- 1. 执行前请备份数据库
-- 2. 此脚本为 WorkflowInstance 架构提供数据库支持
-- 3. 包含：WorkflowInstance 表、NodeExecution 表、APScheduler 任务表
-- 4. 旧数据将保留，新执行的工作流将使用新架构
