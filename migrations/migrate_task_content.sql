-- Migration: Add task_content column to manual_task table
-- Compatible with MySQL 5.7+
-- Run: mysql -u root -p contact_mail < migrate_task_content.sql

ALTER TABLE manual_task ADD COLUMN task_content TEXT NULL COMMENT 'Manual task work content' AFTER title;