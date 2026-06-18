-- Affiliate 联盟营销数据持久化
CREATE TABLE IF NOT EXISTS referral (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    referrer_id INT NOT NULL COMMENT '推荐人用户ID',
    code VARCHAR(20) NOT NULL UNIQUE COMMENT '推荐码',
    click_count INT NOT NULL DEFAULT 0 COMMENT '点击次数',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    INDEX idx_referral_referrer (referrer_id),
    INDEX idx_referral_code (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='推荐链接表';

CREATE TABLE IF NOT EXISTS referral_click (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    referral_id INT NOT NULL COMMENT '关联 referral.id',
    ip VARCHAR(50) DEFAULT '' COMMENT '访问者IP',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '点击时间',
    INDEX idx_rclick_referral (referral_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='推荐链接点击记录';

CREATE TABLE IF NOT EXISTS referral_signup (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    referral_id INT NOT NULL COMMENT '关联 referral.id',
    new_user_id INT NOT NULL COMMENT '新注册用户ID',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '注册时间',
    INDEX idx_rsignup_referral (referral_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='推荐注册记录';

CREATE TABLE IF NOT EXISTS commission (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    referrer_id INT NOT NULL COMMENT '推荐人用户ID',
    amount DECIMAL(10,2) NOT NULL DEFAULT 0 COMMENT '佣金金额',
    status VARCHAR(20) NOT NULL DEFAULT 'pending' COMMENT '状态: pending/paid',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    INDEX idx_commission_referrer (referrer_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='佣金记录';