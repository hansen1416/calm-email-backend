#!/usr/bin/env python3
"""
执行数据库迁移脚本
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

def execute_migration():
    """执行迁移脚本"""
    db_uri = os.getenv('DATABASE_URI', 'mysql+pymysql://root:root@192.168.56.131:3306/contact_mail')
    engine = create_engine(db_uri)
    
    print("="*60)
    print("Executing Database Migration")
    print("="*60)
    
    with engine.connect() as conn:
        # 检查字段是否已存在
        result = conn.execute(text("""
            SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'email_event'
            AND COLUMN_NAME = 'sns_message_id'
        """)).fetchone()
        
        if result:
            print("[INFO] Fields already exist, skipping migration")
            return True
        
        # 添加新字段
        print("[1/4] Adding sns_message_id column...")
        conn.execute(text("""
            ALTER TABLE email_event
            ADD COLUMN sns_message_id VARCHAR(100) NULL COMMENT 'SNS 消息唯一ID，用于去重'
        """))
        
        print("[2/4] Adding sns_received_at column...")
        conn.execute(text("""
            ALTER TABLE email_event
            ADD COLUMN sns_received_at DATETIME NULL COMMENT 'SNS 消息接收时间，用于计算回调延迟'
        """))
        
        print("[3/4] Adding sns_delay_seconds column...")
        conn.execute(text("""
            ALTER TABLE email_event
            ADD COLUMN sns_delay_seconds FLOAT NULL COMMENT 'SNS 回调延迟秒数'
        """))
        
        print("[4/4] Creating unique index...")
        try:
            conn.execute(text("""
                CREATE UNIQUE INDEX idx_emailevent_sns_message_id ON email_event(sns_message_id)
            """))
        except Exception as e:
            print(f"[WARNING] Unique index may already exist: {e}")
        
        conn.commit()
        
        print("\n[SUCCESS] Migration completed!")
        print("\nAdded fields:")
        print("  - sns_message_id (VARCHAR 100, UNIQUE)")
        print("  - sns_received_at (DATETIME)")
        print("  - sns_delay_seconds (FLOAT)")
        
        # 验证
        result = conn.execute(text("DESCRIBE email_event")).fetchall()
        print("\nCurrent email_event table structure:")
        for row in result:
            if row[0] in ['sns_message_id', 'sns_received_at', 'sns_delay_seconds']:
                print(f"  [OK] {row[0]}: {row[1]}")
        
        return True

if __name__ == '__main__':
    try:
        execute_migration()
    except Exception as e:
        print(f"\n[ERROR] Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
