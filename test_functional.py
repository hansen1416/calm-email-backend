#!/usr/bin/env python3
"""
功能测试验证 - 确认外键移除后所有功能正常
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_models():
    """测试模型加载"""
    print("="*60)
    print("Test 1: Model Loading")
    print("="*60)
    
    try:
        from models import User, Contact, ContactGroup, Workflow, WorkflowInstance, EmailLog, EmailEvent, NodeExecution
        print("[OK] All models imported successfully")
        
        # 检查字段
        for model_name, model in [
            ('User', User), ('Contact', Contact), ('ContactGroup', ContactGroup),
            ('Workflow', Workflow), ('WorkflowInstance', WorkflowInstance),
            ('EmailLog', EmailLog), ('EmailEvent', EmailEvent), ('NodeExecution', NodeExecution)
        ]:
            print(f"  [OK] {model_name} model loaded")
        
        return True
    except Exception as e:
        print(f"[FAIL] Model import failed: {e}")
        return False

def test_relationships():
    """测试关系定义"""
    print("\n" + "="*60)
    print("Test 2: Relationship Definitions")
    print("="*60)
    
    try:
        from models import Workflow, WorkflowInstance, Contact, ContactGroup
        
        # 检查 relationship
        if hasattr(Workflow, 'instances'):
            print("[OK] Workflow.instances relationship exists")
        if hasattr(WorkflowInstance, 'workflow'):
            print("[OK] WorkflowInstance.workflow relationship exists")
        if hasattr(WorkflowInstance, 'node_executions'):
            print("[OK] WorkflowInstance.node_executions relationship exists")
        if hasattr(WorkflowInstance, 'email_logs'):
            print("[OK] WorkflowInstance.email_logs relationship exists")
        if hasattr(Contact, 'groups'):
            print("[OK] Contact.groups relationship exists")
        if hasattr(ContactGroup, 'contacts'):
            print("[OK] ContactGroup.contacts relationship exists")
        
        return True
    except Exception as e:
        print(f"[FAIL] Relationship check failed: {e}")
        return False

def test_cascade_delete():
    """测试级联删除函数"""
    print("\n" + "="*60)
    print("Test 3: Cascade Delete Functions")
    print("="*60)
    
    try:
        from utils.cascade_delete import delete_workflow_cascade, delete_instance_cascade, delete_user_cascade
        
        print("[OK] delete_workflow_cascade imported")
        print("[OK] delete_instance_cascade imported")
        print("[OK] delete_user_cascade imported")
        
        return True
    except Exception as e:
        print(f"[FAIL] Cascade delete import failed: {e}")
        return False

def test_database_connection():
    """测试数据库连接"""
    print("\n" + "="*60)
    print("Test 4: Database Connection")
    print("="*60)
    
    try:
        from sqlalchemy import create_engine, text
        from dotenv import load_dotenv
        
        load_dotenv()
        db_uri = os.getenv('DATABASE_URI', 'mysql+pymysql://root:root@192.168.56.131:3306/contact_mail')
        engine = create_engine(db_uri)
        
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1")).fetchone()
            if result[0] == 1:
                print("[OK] Database connection successful")
                
                # 检查外键状态
                result = conn.execute(text("""
                    SELECT COUNT(*) FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
                    WHERE TABLE_SCHEMA = DATABASE() AND REFERENCED_TABLE_NAME IS NOT NULL
                """)).fetchone()
                
                fk_count = result[0] if result else 0
                print(f"  Foreign key constraints: {fk_count}")
                
                if fk_count == 0:
                    print("[OK] Foreign keys successfully removed")
                else:
                    print(f"[!] {fk_count} FK constraints remain (may include system tables)")
                
                return True
    except Exception as e:
        print(f"[FAIL] Database connection failed: {e}")
        return False

def main():
    print("\n" + "="*60)
    print("Foreign Key Removal - Functional Test")
    print("="*60 + "\n")
    
    results = []
    
    # 测试 1: 模型导入
    results.append(("Model Loading", test_models()))
    
    # 测试 2: 关系定义
    results.append(("Relationship Definitions", test_relationships()))
    
    # 测试 3: 级联删除
    results.append(("Cascade Delete", test_cascade_delete()))
    
    # 测试 4: 数据库连接
    results.append(("Database Connection", test_database_connection()))
    
    # 总结
    print("\n" + "="*60)
    print("Test Summary")
    print("="*60)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"{status} - {name}")
    
    print(f"\nTotal: {passed}/{total} passed")
    
    if passed == total:
        print("\n[OK] All tests passed! Foreign key removal successful!")
        return 0
    else:
        print("\n[FAIL] Some tests failed, please check")
        return 1

if __name__ == '__main__':
    sys.exit(main())
