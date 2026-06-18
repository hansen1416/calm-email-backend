-- OAuth2 配置持久化到数据库
CREATE TABLE IF NOT EXISTS oauth_config (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    user_id INT NOT NULL COMMENT '用户ID',
    provider VARCHAR(20) NOT NULL COMMENT '提供商: google/outlook',
    client_id VARCHAR(512) NOT NULL DEFAULT '' COMMENT 'OAuth Client ID',
    client_secret VARCHAR(512) NOT NULL DEFAULT '' COMMENT 'OAuth Client Secret',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    INDEX idx_oauth_config_user_id (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='OAuth2 配置表';