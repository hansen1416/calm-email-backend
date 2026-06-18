-- ============================================================
-- CalmOS P0-P2 数据库变更汇总
-- 兼容: MySQL 5.7+
-- 日期: 2026-06-15
-- ============================================================

-- ============================================================
-- P0-1: EmailTemplate 新增 blocks 列 (Editor.js Block数据)
-- ============================================================
ALTER TABLE `email_template`
  ADD COLUMN `blocks` JSON NULL COMMENT 'Editor.js Block数据（JSON格式）'
  AFTER `body`;

-- ============================================================
-- P0-2 + P1-7: Contact 新增 custom_fields 和 status 列
-- ============================================================
ALTER TABLE `contact`
  ADD COLUMN `custom_fields` JSON NULL COMMENT '自定义字段（JSON格式）'
  AFTER `notes`;

ALTER TABLE `contact`
  ADD COLUMN `status` VARCHAR(20) NOT NULL DEFAULT 'active' COMMENT '状态: active-正常, dnc-勿扰'
  AFTER `custom_fields`;

ALTER TABLE `user`
  ADD COLUMN `avatar` VARCHAR(50) NOT NULL DEFAULT 'avatar-1' COMMENT '头像'
  AFTER `custom_fields`;

-- ============================================================
-- P0-3: Segment 动态分段表 (新表)
-- ============================================================
CREATE TABLE IF NOT EXISTS `segment` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '分段ID',
  `user_id` INT NOT NULL COMMENT '所属用户ID',
  `name` VARCHAR(100) NOT NULL COMMENT '分段名称',
  `description` VARCHAR(255) NULL COMMENT '分段描述',
  `rules` JSON NOT NULL COMMENT '规则列表（JSON数组）',
  `match_type` VARCHAR(10) NOT NULL DEFAULT 'all' COMMENT '匹配模式: all-AND, any-OR',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  INDEX `idx_segment_user_id` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='动态分段表';

-- ============================================================
-- P1-6: ManualTask 人工任务表 (新表)
-- ============================================================
CREATE TABLE IF NOT EXISTS `manual_task` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '任务ID',
  `user_id` INT NOT NULL COMMENT '所属用户ID',
  `instance_id` INT NULL COMMENT '关联的工作流实例ID',
  `workflow_name` VARCHAR(100) NULL COMMENT '工作流名称',
  `contact_name` VARCHAR(100) NULL COMMENT '联系人姓名',
  `contact_email` VARCHAR(120) NULL COMMENT '联系人邮箱',
  `title` VARCHAR(200) NOT NULL COMMENT '任务标题',
  `description` TEXT NULL COMMENT '任务描述',
  `node_id` VARCHAR(50) NULL COMMENT '触发此任务的节点ID',
  `status` VARCHAR(20) NOT NULL DEFAULT 'pending' COMMENT '任务状态: pending/completed/cancelled',
  `result` TEXT NULL COMMENT '任务完成结果',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `completed_at` DATETIME NULL COMMENT '完成时间',
  `completed_by` INT NULL COMMENT '完成人用户ID',
  PRIMARY KEY (`id`),
  INDEX `idx_mtask_user_id` (`user_id`),
  INDEX `idx_mtask_instance_id` (`instance_id`),
  INDEX `idx_mtask_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='人工任务表';

-- ============================================================
-- 验证: 检查所有变更是否生效
-- ============================================================
-- 查看 email_template 列
-- DESC email_template;
-- 查看 contact 列
-- DESC contact;
-- 检查新表
-- SHOW TABLES LIKE 'segment';
-- SHOW TABLES LIKE 'manual_task';