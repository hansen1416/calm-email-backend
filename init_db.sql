-- ========================================-- Mail Flow 数据库初始化脚本-- 包含所有表结构和索引-- 适用于 MySQL 8.0+-- ========================================
-- 设置字符集
SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ========================================-- 1. 创建数据库-- ========================================CREATE DATABASE IF NOT EXISTS contact_mail_prod
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_unicode_ci;

USE contact_mail_prod;

-- ========================================-- 2. 用户表-- ========================================CREATE TABLE IF NOT EXISTS `user` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `username` VARCHAR(80) NOT NULL UNIQUE,
    `password_hash` VARCHAR(256) NOT NULL,
    `email` VARCHAR(120) DEFAULT NULL,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ========================================-- 3. 联系人表-- ========================================CREATE TABLE IF NOT EXISTS `contact` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `user_id` INT NOT NULL,
    `name` VARCHAR(100) NOT NULL,
    `email` VARCHAR(120) NOT NULL,
    `phone` VARCHAR(30) DEFAULT NULL,
    `company` VARCHAR(100) DEFAULT NULL,
    `notes` TEXT DEFAULT NULL,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX `idx_contact_user_id` (`user_id`),
    INDEX `idx_contact_email` (`email`),
    FOREIGN KEY (`user_id`) REFERENCES `user`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ========================================-- 4. 联系人群组表-- ========================================CREATE TABLE IF NOT EXISTS `contact_group` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `user_id` INT NOT NULL,
    `name` VARCHAR(100) NOT NULL,
    `description` VARCHAR(255) DEFAULT NULL,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`user_id`) REFERENCES `user`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ========================================-- 5. 群组-联系人关联表-- ========================================CREATE TABLE IF NOT EXISTS `group_contacts` (
    `group_id` INT NOT NULL,
    `contact_id` INT NOT NULL,
    PRIMARY KEY (`group_id`, `contact_id`),
    FOREIGN KEY (`group_id`) REFERENCES `contact_group`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`contact_id`) REFERENCES `contact`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ========================================-- 6. 邮件模板表-- ========================================CREATE TABLE IF NOT EXISTS `email_template` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `user_id` INT NOT NULL,
    `name` VARCHAR(100) NOT NULL,
    `subject` VARCHAR(255) NOT NULL,
    `body` TEXT NOT NULL,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (`user_id`) REFERENCES `user`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ========================================-- 7. 工作流表-- ========================================CREATE TABLE IF NOT EXISTS `workflow` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `user_id` INT NOT NULL,
    `name` VARCHAR(100) NOT NULL,
    `flow_data` TEXT NOT NULL,
    `status` VARCHAR(20) DEFAULT 'inactive',
    `execution_mode` VARCHAR(20) DEFAULT 'manual',
    `start_time` DATETIME DEFAULT NULL,
    `last_executed_at` DATETIME DEFAULT NULL,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (`user_id`) REFERENCES `user`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ========================================-- 8. 工作流实例表-- ========================================CREATE TABLE IF NOT EXISTS `workflow_instance` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `workflow_id` INT NOT NULL,
    `user_id` INT NOT NULL,
    `recipient_email` VARCHAR(120) NOT NULL,
    `message_id` VARCHAR(100) DEFAULT NULL,
    `status` VARCHAR(20) DEFAULT 'pending',
    `current_node_id` VARCHAR(50) DEFAULT NULL,
    `waiting_event_type` VARCHAR(20) DEFAULT NULL,
    `waiting_conditions` JSON DEFAULT NULL,
    `waiting_since` DATETIME DEFAULT NULL,
    `context` JSON DEFAULT NULL,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    `completed_at` DATETIME DEFAULT NULL,
    INDEX `idx_instance_workflow_id` (`workflow_id`),
    INDEX `idx_instance_user_id` (`user_id`),
    INDEX `idx_instance_status` (`status`),
    INDEX `idx_instance_message_id` (`message_id`),
    INDEX `idx_instance_created_at` (`created_at`),
    FOREIGN KEY (`workflow_id`) REFERENCES `workflow`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`user_id`) REFERENCES `user`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ========================================-- 9. 邮件日志表-- ========================================CREATE TABLE IF NOT EXISTS `email_log` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `user_id` INT NOT NULL,
    `template_id` INT DEFAULT NULL,
    `workflow_id` INT DEFAULT NULL,
    `instance_id` INT DEFAULT NULL,
    `node_id` VARCHAR(50) DEFAULT NULL,
    `source_event_id` INT DEFAULT NULL,
    `recipient_email` VARCHAR(120) NOT NULL,
    `subject` VARCHAR(255) NOT NULL,
    `message_id` VARCHAR(100) DEFAULT NULL,
    `status` VARCHAR(20) DEFAULT 'sent',
    `sent_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_emaillog_user_id` (`user_id`),
    INDEX `idx_emaillog_instance_id` (`instance_id`),
    INDEX `idx_emaillog_message_id` (`message_id`),
    INDEX `idx_emaillog_sent_at` (`sent_at`),
    FOREIGN KEY (`user_id`) REFERENCES `user`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`template_id`) REFERENCES `email_template`(`id`) ON DELETE SET NULL,
    FOREIGN KEY (`workflow_id`) REFERENCES `workflow`(`id`) ON DELETE SET NULL,
    FOREIGN KEY (`instance_id`) REFERENCES `workflow_instance`(`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ========================================-- 10. 邮件事件表-- ========================================CREATE TABLE IF NOT EXISTS `email_event` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `user_id` INT NOT NULL,
    `instance_id` INT DEFAULT NULL,
    `message_id` VARCHAR(100) DEFAULT NULL,
    `event_type` VARCHAR(20) NOT NULL,
    `recipient_email` VARCHAR(120) NOT NULL,
    `event_data` JSON DEFAULT NULL,
    `occurred_at` DATETIME DEFAULT NULL,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_emailevent_message_id` (`message_id`),
    INDEX `idx_emailevent_event_type` (`event_type`),
    INDEX `idx_emailevent_created_at` (`created_at`),
    FOREIGN KEY (`user_id`) REFERENCES `user`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`instance_id`) REFERENCES `workflow_instance`(`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ========================================-- 11. 节点执行记录表-- ========================================CREATE TABLE IF NOT EXISTS `node_execution` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `instance_id` INT NOT NULL,
    `node_id` VARCHAR(50) NOT NULL,
    `node_type` VARCHAR(20) NOT NULL,
    `node_label` VARCHAR(100) DEFAULT NULL,
    `result` VARCHAR(20) NOT NULL,
    `input_data` JSON DEFAULT NULL,
    `output_data` JSON DEFAULT NULL,
    `resumed_by_event_id` INT DEFAULT NULL,
    `event_data` JSON DEFAULT NULL,
    `conditions_met` TINYINT(1) DEFAULT NULL,
    `error_message` TEXT DEFAULT NULL,
    `executed_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `completed_at` DATETIME DEFAULT NULL,
    `duration_ms` INT DEFAULT NULL,
    INDEX `idx_nodeexecution_instance_id` (`instance_id`),
    INDEX `idx_nodeexecution_node_id` (`node_id`),
    INDEX `idx_nodeexecution_result` (`result`),
    INDEX `idx_nodeexecution_executed_at` (`executed_at`),
    FOREIGN KEY (`instance_id`) REFERENCES `workflow_instance`(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`resumed_by_event_id`) REFERENCES `email_event`(`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ========================================-- 12. APScheduler 任务表-- ========================================CREATE TABLE IF NOT EXISTS `apscheduler_jobs` (
    `id` VARCHAR(191) NOT NULL PRIMARY KEY,
    `next_run_time` DOUBLE PRECISION DEFAULT NULL,
    `job_state` BLOB NOT NULL,
    INDEX `idx_apscheduler_next_run_time` (`next_run_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ========================================-- 13. 创建默认管理员用户（可选）-- 密码: admin123-- 密码哈希使用 werkzeug.security.generate_password_hash 生成-- ========================================-- INSERT INTO `user` (`username`, `password_hash`, `email`) VALUES 
-- ('admin', 'scrypt:32768:8:1$...', 'admin@example.com');

SET FOREIGN_KEY_CHECKS = 1;

-- ========================================-- 完成提示-- ========================================SELECT 'Database initialized successfully!' AS status;
