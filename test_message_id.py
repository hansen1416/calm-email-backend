#!/usr/bin/env python3
"""
测试工作流执行中的 message_id 一致性
使用 workflow_id=3 进行测试
"""

import requests
import json
import time
from datetime import datetime

# 配置
BASE_URL = "http://localhost:8880"
# 需要先登录获取 JWT token
# 假设用户已登录，token 为：
TOKEN = None

def get_jwt_token():
    """获取 JWT token"""
    global TOKEN
    # 尝试登录
    try:
        resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "test",
            "password": "test123"
        })
        if resp.status_code == 200:
            TOKEN = resp.json().get('access_token')
            print(f"✓ Got JWT token: {TOKEN[:20]}...")
            return TOKEN
        else:
            print(f"✗ Login failed: {resp.status_code}")
            return None
    except Exception as e:
        print(f"✗ Login error: {e}")
        return None

def execute_workflow(workflow_id=3):
    """执行工作流"""
    headers = {"Authorization": f"Bearer {TOKEN}"}
    resp = requests.post(f"{BASE_URL}/api/workflow/{workflow_id}/execute", 
                        headers=headers,
                        json={"mock": True})
    
    if resp.status_code == 200:
        data = resp.json()
        print(f"✓ Workflow executed: {data}")
        return data.get('instances', [])
    else:
        print(f"✗ Workflow execution failed: {resp.status_code} - {resp.text}")
        return []

def get_instance_details(instance_id):
    """获取实例详情"""
    headers = {"Authorization": f"Bearer {TOKEN}"}
    resp = requests.get(f"{BASE_URL}/api/instance/{instance_id}", headers=headers)
    
    if resp.status_code == 200:
        data = resp.json()
        return data
    else:
        print(f"✗ Get instance failed: {resp.status_code} - {resp.text}")
        return None

def simulate_event(message_id, recipient_email="ice_br2046@163.com", event_type="open"):
    """模拟事件触发"""
    headers = {"Authorization": f"Bearer {TOKEN}"}
    
    event_data = {
        "event_type": event_type,
        "message_id": message_id,
        "recipient_email": recipient_email,
        "event_data": {
            "eventType": event_type,
            "mail": {
                "messageId": message_id,
                "commonHeaders": {
                    "to": [recipient_email]
                }
            }
        },
        "mock_send": True
    }
    
    resp = requests.post(f"{BASE_URL}/api/webhooks/simulate/event",
                        headers=headers,
                        json=event_data)
    
    if resp.status_code == 200:
        data = resp.json()
        print(f"✓ Event simulated: {data}")
        return data
    else:
        print(f"✗ Event simulation failed: {resp.status_code} - {resp.text}")
        return None

def check_database_records(instance_id):
    """检查数据库记录"""
    print(f"\n=== Checking Database Records for Instance {instance_id} ===")
    
    try:
        from sqlalchemy import create_engine, text
        import os
        from dotenv import load_dotenv
        load_dotenv()
        
        db_uri = os.getenv('DATABASE_URI', 'mysql+pymysql://root:root@192.168.56.131:3306/contact_mail')
        engine = create_engine(db_uri)
        
        with engine.connect() as conn:
            # 检查 WorkflowInstance
            result = conn.execute(text(
                f"SELECT id, message_id, recipient_email, status FROM workflow_instance WHERE id = {instance_id}"
            )).fetchone()
            
            if result:
                print(f"\nWorkflowInstance:")
                print(f"  ID: {result[0]}")
                print(f"  message_id: {result[1]}")
                print(f"  recipient: {result[2]}")
                print(f"  status: {result[3]}")
            
            # 检查 EmailLog
            result = conn.execute(text(
                f"SELECT id, message_id, recipient_email, subject, source_event_id FROM email_log WHERE instance_id = {instance_id} ORDER BY id"
            )).fetchall()
            
            print(f"\nEmailLog Records ({len(result)}):")
            for row in result:
                print(f"  [{row[0]}] msg_id={row[1]}, recipient={row[2]}, subject={row[3]}, source_event_id={row[4]}")
            
            # 检查 EmailEvent
            result = conn.execute(text(
                f"SELECT id, message_id, event_type, source_email_log_id FROM email_event WHERE instance_id = {instance_id}"
            )).fetchall()
            
            print(f"\nEmailEvent Records ({len(result)}):")
            for row in result:
                print(f"  [{row[0]}] msg_id={row[1]}, type={row[2]}, source_email_log_id={row[3]}")
            
            # 检查 NodeExecution
            result = conn.execute(text(
                f"SELECT id, node_id, node_type, result, resumed_by_event_id FROM node_execution WHERE instance_id = {instance_id} ORDER BY id"
            )).fetchall()
            
            print(f"\nNodeExecution Records ({len(result)}):")
            for row in result:
                print(f"  [{row[0]}] node={row[1]}, type={row[2]}, result={row[3]}, resumed_by_event_id={row[4]}")
            
            return True
    except Exception as e:
        print(f"✗ Database check failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    print("="*60)
    print("Message ID Consistency Test")
    print("="*60)
    
    # 获取 token
    if not get_jwt_token():
        print("✗ Cannot proceed without JWT token")
        return
    
    # 执行工作流
    print("\n--- Step 1: Execute Workflow ---")
    instances = execute_workflow(workflow_id=3)
    
    if not instances:
        print("✗ No instances created")
        return
    
    instance_id = instances[0].get('id')
    recipient_email = instances[0].get('recipient_email')
    print(f"✓ Created instance {instance_id} for {recipient_email}")
    
    # 等待工作流执行到 driver 节点
    print("\n--- Step 2: Wait for Driver Node ---")
    time.sleep(2)
    
    # 获取实例详情
    details = get_instance_details(instance_id)
    if details:
        instance = details.get('instance', {})
        message_id = instance.get('message_id')
        status = instance.get('status')
        print(f"Instance status: {status}")
        print(f"Instance message_id: {message_id}")
    
    # 检查数据库
    check_database_records(instance_id)
    
    if status != 'waiting_event' or not message_id:
        print(f"✗ Instance not in expected state (waiting_event)")
        return
    
    # 模拟事件
    print("\n--- Step 3: Simulate Event ---")
    event_result = simulate_event(message_id, recipient_email, "send")
    
    if not event_result:
        print("✗ Event simulation failed")
        return
    
    # 等待延时任务执行
    print("\n--- Step 4: Wait for Delay Task ---")
    print("Waiting 65 seconds for delay task (1 minute delay + buffer)...")
    time.sleep(65)
    
    # 再次检查数据库
    check_database_records(instance_id)
    
    # 获取最终实例状态
    print("\n--- Step 5: Final Status ---")
    details = get_instance_details(instance_id)
    if details:
        instance = details.get('instance', {})
        print(f"Final status: {instance.get('status')}")
    
    print("\n" + "="*60)
    print("Test Completed")
    print("="*60)

if __name__ == "__main__":
    main()
