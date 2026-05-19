-- M11: Stripe 支付 - 插入5档套餐数据
-- 英国市场 / GBP 定价，MySQL 5.7 兼容
-- 日期: 2026-05-19

-- 使用 INSERT ... ON DUPLICATE KEY UPDATE 避免自增计数器混乱
-- 如果记录已存在则更新价格，不存在则插入

-- Free (默认套餐)
INSERT INTO email_quota_config (id, name, daily_limit, description, is_default, price_monthly, price_yearly, created_at)
VALUES (1, 'Free', 100, 'Free tier: 100 emails/day, no credit card required', TRUE, NULL, NULL, NOW())
ON DUPLICATE KEY UPDATE
    name = VALUES(name),
    daily_limit = VALUES(daily_limit),
    description = VALUES(description),
    is_default = VALUES(is_default),
    price_monthly = VALUES(price_monthly),
    price_yearly = VALUES(price_yearly);

-- Starter
INSERT INTO email_quota_config (id, name, daily_limit, description, is_default, price_monthly, price_yearly, created_at)
VALUES (2, 'Starter', 500, 'For individuals and freelancers: 500 emails/day', FALSE, 399, 3990, NOW())
ON DUPLICATE KEY UPDATE
    name = VALUES(name),
    daily_limit = VALUES(daily_limit),
    description = VALUES(description),
    is_default = VALUES(is_default),
    price_monthly = VALUES(price_monthly),
    price_yearly = VALUES(price_yearly);

-- Growth
INSERT INTO email_quota_config (id, name, daily_limit, description, is_default, price_monthly, price_yearly, created_at)
VALUES (3, 'Growth', 2000, 'For small teams: 2,000 emails/day', FALSE, 699, 6990, NOW())
ON DUPLICATE KEY UPDATE
    name = VALUES(name),
    daily_limit = VALUES(daily_limit),
    description = VALUES(description),
    is_default = VALUES(is_default),
    price_monthly = VALUES(price_monthly),
    price_yearly = VALUES(price_yearly);

-- Business
INSERT INTO email_quota_config (id, name, daily_limit, description, is_default, price_monthly, price_yearly, created_at)
VALUES (4, 'Business', 5000, 'For growing companies: 5,000 emails/day', FALSE, 1299, 12990, NOW())
ON DUPLICATE KEY UPDATE
    name = VALUES(name),
    daily_limit = VALUES(daily_limit),
    description = VALUES(description),
    is_default = VALUES(is_default),
    price_monthly = VALUES(price_monthly),
    price_yearly = VALUES(price_yearly);

-- Enterprise
INSERT INTO email_quota_config (id, name, daily_limit, description, is_default, price_monthly, price_yearly, created_at)
VALUES (5, 'Enterprise', 10000, 'For large organizations: 10,000 emails/day', FALSE, 2499, 24990, NOW())
ON DUPLICATE KEY UPDATE
    name = VALUES(name),
    daily_limit = VALUES(daily_limit),
    description = VALUES(description),
    is_default = VALUES(is_default),
    price_monthly = VALUES(price_monthly),
    price_yearly = VALUES(price_yearly);

-- 验证插入结果
SELECT id, name, daily_limit,
       CONCAT('£', price_monthly/100) AS monthly_price,
       CONCAT('£', price_yearly/100) AS yearly_price,
       is_default
FROM email_quota_config
ORDER BY daily_limit;