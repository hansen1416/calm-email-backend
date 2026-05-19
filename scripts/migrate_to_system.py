"""
系统域名迁移脚本
M9: 从 personal 模式迁移到 system 模式

说明:
- 此脚本用于将用户从 personal 模式迁移到 system 模式
- 为每个用户生成系统子邮箱
- 保留原 personal 绑定记录（用于历史追溯）
- 执行前请备份数据库

使用方法:
1. 备份数据库
2. 配置 SYSTEM_DOMAIN 和 SYSTEM_SENDER_PREFIX
3. 运行: python migrate_to_system.py
4. 修改 .env: EMAIL_SENDER_MODE=system
5. 重启服务

迁移流程:
1. 检查配置
2. 验证系统域名在SES中已验证
3. 为每个用户生成系统子邮箱
4. 创建新的 binding 记录（system类型）
5. 保持原 personal 记录（标记为非默认）
6. 生成迁移报告
"""

import sys
import os

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from models import db, User, UserSenderBinding, EmailQuotaConfig
from datetime import datetime


def check_migration_config(app):
    """检查迁移配置"""
    system_domain = app.config.get('SYSTEM_DOMAIN', '')
    sender_prefix = app.config.get('SYSTEM_SENDER_PREFIX', 'user')
    
    if not system_domain:
        print("❌ 错误: SYSTEM_DOMAIN 未配置")
        print("   请在 .env 中设置 SYSTEM_DOMAIN=mail.yourdomain.com")
        return False
    
    print(f"✓ 系统域名: {system_domain}")
    print(f"✓ 邮箱前缀: {sender_prefix}")
    return True


def verify_system_domain_in_ses(app):
    """验证系统域名在SES中已验证（可选）"""
    import boto3
    
    try:
        client = boto3.client(
            'ses',
            region_name=app.config['AWS_REGION'],
            aws_access_key_id=app.config['AWS_ACCESS_KEY_ID'],
            aws_secret_access_key=app.config['AWS_SECRET_ACCESS_KEY']
        )
        
        system_domain = app.config['SYSTEM_DOMAIN']
        
        # 获取已验证的域名
        response = client.list_identities(IdentityType='Domain')
        verified_domains = response.get('Identities', [])
        
        if system_domain in verified_domains:
            print(f"✓ 系统域名 {system_domain} 已在SES中验证")
            return True
        else:
            print(f"⚠ 警告: 系统域名 {system_domain} 未在SES中验证")
            print(f"   已验证的域名: {verified_domains}")
            print(f"\n   建议: 在SES控制台验证域名后再执行迁移")
            print(f"   或者继续执行（新绑定将等待验证）")
            
            # 询问是否继续
            response = input("\n是否继续? [y/N]: ")
            if response.lower() != 'y':
                return False
        
        return True
        
    except Exception as e:
        print(f"⚠ 无法验证SES域名状态: {e}")
        print("   建议: 手动检查域名验证状态")
        return True  # 不阻塞迁移


def get_default_quota_id(app):
    """获取默认配额配置ID"""
    config = EmailQuotaConfig.query.filter_by(is_default=True).first()
    
    if not config:
        # 创建默认配置
        config = EmailQuotaConfig(
            name='free',
            daily_limit=app.config.get('DEFAULT_DAILY_QUOTA', 100),
            description='Free tier (auto-created during migration)',
            is_default=True
        )
        db.session.add(config)
        db.session.commit()
        print(f"✓ 创建默认配额配置: ID={config.id}")
    
    return config.id


def generate_system_email(user_id, prefix, domain):
    """生成系统子邮箱"""
    # 格式: prefix0001@domain
    user_number = str(user_id).zfill(4)
    return f"{prefix}{user_number}@{domain}"


def migrate_user(app, user, quota_config_id, prefix, domain):
    """
    迁移单个用户
    
    1. 取消现有默认绑定
    2. 生成系统子邮箱
    3. 创建新的 binding 记录
    4. 保持原记录（非默认）
    """
    user_id = user.id
    system_email = generate_system_email(user_id, prefix, domain)
    
    # 取消现有默认
    UserSenderBinding.query.filter_by(
        user_id=user_id,
        is_default=True
    ).update({'is_default': False})
    
    # 检查是否已存在系统邮箱
    existing = UserSenderBinding.query.filter_by(
        user_id=user_id,
        email=system_email
    ).first()
    
    if existing:
        print(f"  ⚠ 用户 {user_id} 已存在系统邮箱: {system_email}")
        existing.is_default = True
        existing.is_active = True
        db.session.commit()
        return True, "already_exists"
    
    # 创建新的系统绑定
    binding = UserSenderBinding(
        user_id=user_id,
        email=system_email,
        email_type='system',
        real_email=user.email,  # 使用用户注册邮箱作为 Reply-To
        ses_identity_status='verified',  # 域名已验证，子邮箱自动可用
        quota_config_id=quota_config_id,
        is_default=True,
        is_active=True
    )
    
    db.session.add(binding)
    db.session.commit()
    
    print(f"  ✓ 创建系统邮箱: {system_email}")
    return True, "created"


def run_migration():
    """执行迁移"""
    print("=" * 60)
    print("MailFlow 系统域名迁移脚本")
    print("=" * 60)
    print()
    
    # 创建应用上下文
    app = create_app()
    
    with app.app_context():
        # 1. 检查配置
        print("\n[1/4] 检查配置...")
        if not check_migration_config(app):
            return 1
        
        system_domain = app.config['SYSTEM_DOMAIN']
        sender_prefix = app.config['SYSTEM_SENDER_PREFIX']
        
        # 2. 验证SES域名（可选）
        print("\n[2/4] 验证SES域名状态...")
        if not verify_system_domain_in_ses(app):
            return 1
        
        # 3. 确认迁移
        user_count = User.query.count()
        print(f"\n[3/4] 准备迁移 {user_count} 个用户...")
        print(f"\n迁移计划:")
        print(f"  - 系统域名: {system_domain}")
        print(f"  - 邮箱格式: {sender_prefix}0001@{system_domain}")
        print(f"  - 受影响用户: {user_count}")
        print(f"\n⚠ 警告: 此操作将修改用户发件邮箱配置")
        print(f"⚠ 建议在执行前备份数据库")
        
        response = input("\n是否确认执行? 输入 'MIGRATE' 继续: ")
        if response != 'MIGRATE':
            print("\n迁移已取消")
            return 0
        
        # 4. 执行迁移
        print("\n[4/4] 执行迁移...")
        
        quota_config_id = get_default_quota_id(app)
        
        success_count = 0
        fail_count = 0
        skip_count = 0
        
        users = User.query.all()
        
        for i, user in enumerate(users, 1):
            print(f"\n[{i}/{user_count}] 用户 ID={user.id}, 用户名={user.username}")
            
            try:
                ok, status = migrate_user(
                    app, user, quota_config_id, sender_prefix, system_domain
                )
                
                if status == "already_exists":
                    skip_count += 1
                elif ok:
                    success_count += 1
                else:
                    fail_count += 1
                    
            except Exception as e:
                print(f"  ❌ 迁移失败: {e}")
                db.session.rollback()
                fail_count += 1
        
        # 5. 生成报告
        print("\n" + "=" * 60)
        print("迁移完成")
        print("=" * 60)
        print(f"\n统计:")
        print(f"  ✓ 成功: {success_count}")
        print(f"  ⚠ 跳过（已存在）: {skip_count}")
        print(f"  ✗ 失败: {fail_count}")
        print(f"\n下一步:")
        print(f"  1. 修改 .env: EMAIL_SENDER_MODE=system")
        print(f"  2. 重启服务")
        print(f"  3. 验证迁移结果")
        
        return 0 if fail_count == 0 else 1


def rollback_migration():
    """
    回滚迁移（预留）
    
    将 system 模式的绑定恢复为 personal 模式
    """
    print("=" * 60)
    print("MailFlow 迁移回滚脚本")
    print("=" * 60)
    print("\n⚠ 警告: 此操作将删除所有 system 类型的绑定")
    
    app = create_app()
    
    with app.app_context():
        system_bindings = UserSenderBinding.query.filter_by(
            email_type='system'
        ).all()
        
        print(f"\n发现 {len(system_bindings)} 个 system 类型绑定")
        
        if not system_bindings:
            print("没有需要回滚的数据")
            return 0
        
        response = input("\n是否删除这些绑定? 输入 'ROLLBACK' 继续: ")
        if response != 'ROLLBACK':
            print("\n回滚已取消")
            return 0
        
        for binding in system_bindings:
            print(f"  删除: {binding.email}")
            db.session.delete(binding)
        
        db.session.commit()
        print(f"\n✓ 已删除 {len(system_bindings)} 个绑定")
        print("\n下一步:")
        print("  1. 修改 .env: EMAIL_SENDER_MODE=personal")
        print("  2. 重启服务")
        
        return 0


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='MailFlow 系统域名迁移工具')
    parser.add_argument(
        'action',
        choices=['migrate', 'rollback'],
        default='migrate',
        nargs='?',
        help='migrate: 执行迁移, rollback: 回滚迁移'
    )
    
    args = parser.parse_args()
    
    if args.action == 'migrate':
        sys.exit(run_migration())
    elif args.action == 'rollback':
        sys.exit(rollback_migration())
