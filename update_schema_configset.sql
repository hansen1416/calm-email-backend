-- SES Configuration Set 支持
-- MySQL 5.7 兼容
-- 添加 configuration_set_name 字段到 user_sender_binding 表

-- 检查字段是否存在，不存在则添加
SET @dbname = DATABASE();
SET @tablename = 'user_sender_binding';
SET @columnname = 'configuration_set_name';

SET @preparedStatement = (SELECT IF(
  (
    SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = @dbname
    AND TABLE_NAME = @tablename
    AND COLUMN_NAME = @columnname
  ) > 0,
  'SELECT "Column already exists";',
  CONCAT(
    'ALTER TABLE ', @tablename, 
    ' ADD COLUMN ', @columnname, ' VARCHAR(100) DEFAULT NULL ',
    'COMMENT "SES配置集名称（预留，优先于全局配置）";'
  )
));

PREPARE addColumnIfNotExists FROM @preparedStatement;
EXECUTE addColumnIfNotExists;
DEALLOCATE PREPARE addColumnIfNotExists;

-- 验证字段添加成功
SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT, COLUMN_COMMENT
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = @dbname
AND TABLE_NAME = @tablename
AND COLUMN_NAME = @columnname;
