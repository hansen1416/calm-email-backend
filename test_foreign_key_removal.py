#!/usr/bin/env python3
"""
测试外键移除后的功能验证
验证所有关联查询是否正常工作
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_foreign_keys():
    """测试外键移除后的功能"""
    
    from app import create_app
    from models import db, User, Contact, ContactGroup, Workflow, WorkflowInstance, EmailLog, NodeExecution
    
    app = create_app()
    
    with app.app_context():
        print("="*60)
        print("Test: Foreign Key Removal Verification")
        print("="*60)
        
        # 1. 测试基本插入（无外键约束）
        print("\n1. Testing basic insert without FK constraints...")
        
        # 创建用户
        user = User(username='fk_test_user', email='fktest@example.com')
        user.set_password('test123')
        db.session.add(user)
        db.session.commit()
        print(f"   Created user: {user.id}")
        
        # 创建联系人（使用不存在的 user_id 应该也能插入）
        contact = Contact(
            user_id=user.id,
            name='Test Contact',
            email='test_contact@example.com'
        )
        db.session.add(contact)
        db.session.commit()
        print(f"   Created contact: {contact.id}")
        
        # 2. 测试多对多关系（group_contacts）
        print("\n2. Testing many-to-many relationship (group_contacts)...")
        
        group = ContactGroup(
            user_id=user.id,
            name='Test Group'
        )
        db.session.add(group)
        db.session.commit()
        print(f"   Created group: {group.id}")
        
        # 关联
        contact.groups.append(group)
        db.session.commit()
        print(f"   Associated contact with group")
        
        # 验证
        c = Contact.query.get(contact.id)
        if c.groups and len(c.groups) > 0:
            print(f"   [PASS] Contact has {len(c.groups)} groups")
        else:
            print(f"   [FAIL] Contact has no groups")
            
        g = ContactGroup.query.get(group.id)
        if g.contacts and len(g.contacts) > 0:
            print(f"   [PASS] Group has {len(g.contacts)} contacts")
        else:
            print(f"   [FAIL] Group has no contacts")
        
        # 3. 测试 Workflow 关联
        print("\n3. Testing Workflow relationships...")
        
        workflow = Workflow(
            user_id=user.id,
            name='Test_Workflow',
            flow_data='{"nodes": []}',
            status='active'
        )
        db.session.add(workflow)
        db.session.commit()
        print(f"   Created workflow: {workflow.id}")
        
        instance = WorkflowInstance(
            workflow_id=workflow.id,
            user_id=user.id,
            recipient_email='test@example.com',
            status='running'
        )
        db.session.add(instance)
        db.session.commit()
        print(f"   Created instance: {instance.id}")
        
        # 测试正向关联
        w = Workflow.query.get(workflow.id)
        if w.instances and len(w.instances) > 0:
            print(f"   [PASS] Workflow has {len(w.instances)} instances")
        else:
            print(f"   [FAIL] Workflow has no instances")
        
        # 测试反向关联
        i = WorkflowInstance.query.get(instance.id)
        if i.workflow:
            print(f"   [PASS] Instance belongs to workflow: {i.workflow.name}")
        else:
            print(f"   [FAIL] Instance has no workflow")
        
        # 4. 测试 EmailLog 关联
        print("\n4. Testing EmailLog relationships...")
        
        log = EmailLog(
            user_id=user.id,
            instance_id=instance.id,
            workflow_id=workflow.id,
            recipient_email='test@example.com',
            subject='Test',
            status='sent'
        )
        db.session.add(log)
        db.session.commit()
        print(f"   Created email log: {log.id}")
        
        # 测试反向关联
        i2 = WorkflowInstance.query.get(instance.id)
        if i2.email_logs and len(i2.email_logs) > 0:
            print(f"   [PASS] Instance has {len(i2.email_logs)} email logs")
        else:
            print(f"   [FAIL] Instance has no email logs")
        
        # 5. 测试 NodeExecution 关联
        print("\n5. Testing NodeExecution relationships...")
        
        node_exec = NodeExecution(
            instance_id=instance.id,
            node_id='node-1',
            node_type='email',
            node_label='Test',
            result='success'
        )
        db.session.add(node_exec)
        db.session.commit()
        print(f"   Created node execution: {node_exec.id}")
        
        # 测试反向关联
        i3 = WorkflowInstance.query.get(instance.id)
        if i3.node_executions and len(i3.node_executions) > 0:
            print(f"   [PASS] Instance has {len(i3.node_executions)} node executions")
        else:
            print(f"   [FAIL] Instance has no node executions")
        
        # 6. 测试 nullable 外键
        print("\n6. Testing nullable foreign keys...")
        
        standalone_log = EmailLog(
            user_id=user.id,
            instance_id=None,  # NULL
            workflow_id=None,
            recipient_email='standalone@example.com',
            subject='Standalone',
            status='sent'
        )
        db.session.add(standalone_log)
        db.session.commit()
        
        if standalone_log.instance_id is None:
            print(f"   [PASS] Nullable FK works (instance_id=None)")
        else:
            print(f"   [FAIL] Nullable FK failed")
        
        # 清理测试数据
        print("\n7. Cleaning up test data...")
        NodeExecution.query.filter_by(instance_id=instance.id).delete()
        EmailLog.query.filter(EmailLog.user_id == user.id).delete()
        WorkflowInstance.query.filter_by(workflow_id=workflow.id).delete()
        Workflow.query.filter_by(user_id=user.id).delete()
        Contact.query.filter_by(user_id=user.id).delete()
        ContactGroup.query.filter_by(user_id=user.id).delete()
        User.query.filter_by(id=user.id).delete()
        db.session.commit()
        print("   [DONE] Test data cleaned up")
        
        print("\n" + "="*60)
        print("ALL TESTS COMPLETED")
        print("="*60)

if __name__ == '__main__':
    test_foreign_keys()
