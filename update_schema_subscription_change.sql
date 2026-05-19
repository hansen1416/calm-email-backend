-- ============================================================
-- Migration: Add change_type + previous_subscription_id
-- to support plan switch (upgrade/downgrade) tracking
-- Run: mysql -u root -p contact_mail < this_file.sql
-- ============================================================

ALTER TABLE `user_subscription`
    ADD COLUMN `change_type` VARCHAR(20) DEFAULT 'new'
        COMMENT '变动类型：new-新购/upgrade-升级/downgrade-降级'
        AFTER `status`,
    ADD COLUMN `previous_subscription_id` INT DEFAULT NULL
        COMMENT '换套餐时关联的上一条订阅记录ID'
        AFTER `change_type`;