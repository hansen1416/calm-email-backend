#!/usr/bin/env python3
"""测试 workflow_id=1 的字段记录 - 使用模拟SNS流程"""

import requests
import time
import json
import sys
sys.path.insert(0, '.')

BASE_URL = "http://localhost:8880"
TOKEN = None

def get_token():
    global TOKEN
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "username": "test",
        "password": "test123"
    })
    if resp.status_code == 200:
        TOKEN = resp.json().get('access_token')
        print(f"OK Got token: {TOKEN[:20]}...")
        return True
    print(f"FAIL Login failed: {resp.status_code}")
    return False

def execute_workflow(wid=1):
    headers = {"Authorization": f"Bearer {TOKEN}"}
    resp = requests.post(f"{BASE_URL}/api/workflow/{wid}/execute",
                         headers=headers, json={"mock": True})
    if resp.status_code == 200:
        data = resp.json()
        instances = data.get('instances', [])
        print(f"OK Executed workflow {wid}, created {len(instances)} instances")
        return instances
    print(f"FAIL Execute failed: {resp.status_code}")
    return []

def get_instance(iid):
    headers = {"Authorization": f"Bearer {TOKEN}"}
    resp = requests.get(f"{BASE_URL}/api/instance/{iid}", headers=headers)
    if resp.status_code == 200:
        return resp.json()
    return None

def simulate_sns_webhook(msg_id, email, event_type="open"):
    """模拟真实的SNS webhook调用（不是simulate_event接口）"""
    headers = {"Authorization": f"Bearer {TOKEN}"}
    
    # 模拟SNS通知格式
    sns_message = {
        "eventType": event_type,
        "mail": {
            "messageId": msg_id,
            "commonHeaders": {
                "to": [email]
            },
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
        },
        event_type: {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
        }
    }
    
    data = {
        "Type": "Notification",
        "MessageId": f"test-{int(time.time())}",
        "Message": json.dumps(sns_message),
        "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    }
    
    resp = requests.post(f"{BASE_URL}/api/webhooks/sns",
                         headers=headers, json=data)
    print(f"SNS webhook response: {resp.status_code}")
    if resp.status_code == 200:
        return resp.json()
    print(f"Response: {resp.text}")
    return None

def check_db():
    from app import app
    from models import db
    from sqlalchemy import text
    with app.app_context():
        print("\n=== NodeExecution ===")
        r = db.session.execute(text(
            'SELECT id, instance_id, node_id, node_type, result, resumed_by_event_id, event_data '
            'FROM node_execution ORDER BY id DESC LIMIT 10'
        )).fetchall()
        for row in r:
            print(f"  id={row[0]}, inst={row[1]}, node={row[2]}, type={row[3]}, result={row[4]}, event_id={row[5]}, has_data={row[6] is not None}")
        
        print("\n=== EmailLog ===")
        r = db.session.execute(text(
            'SELECT id, instance_id, recipient_email, source_event_id, message_id, sender_binding_id, sender_email_type '
            'FROM email_log ORDER BY id DESC LIMIT 10'
        )).fetchall()
        for row in r:
            print(f"  id={row[0]}, inst={row[1]}, email={row[2]}, src_evt={row[3]}, msg_id={row[4][:20] if row[4] else None}, bind_id={row[5]}, type={row[6]}")
        
        print("\n=== EmailEvent ===")
        r = db.session.execute(text(
            'SELECT id, instance_id, event_type, message_id, source_email_log_id FROM email_event ORDER BY id DESC LIMIT 5'
        )).fetchall()
        for row in r:
            print(f"  id={row[0]}, inst={row[1]}, type={row[2]}, msg_id={row[3][:20] if row[3] else None}, log_id={row[4]}")

def main():
    print("="*60)
    print("Field Value Test for workflow_id=1 (via SNS webhook)")
    print("="*60)
    
    if not get_token():
        return
    
    print("\n--- Current DB State ---")
    check_db()
    
    # Execute workflow
    print("\n--- Execute Workflow ---")
    instances = execute_workflow(1)
    if not instances:
        return
    
    iid = instances[0].get('id')
    email = instances[0].get('recipient_email')
    print(f"Instance {iid} for {email}")
    
    time.sleep(2)
    
    # Get status
    details = get_instance(iid)
    if not details:
        return
    
    inst = details.get('instance', {})
    msg_id = inst.get('message_id')
    status = inst.get('status')
    print(f"Status: {status}, message_id: {msg_id}")
    
    if status != 'waiting_event' or not msg_id:
        print(f"Instance not waiting, status={status}")
        return
    
    # 模拟SNS事件（delivery类型触发driver节点）
    print("\n--- Simulate SNS Event ---")
    result = simulate_sns_webhook(msg_id, email, "delivery")
    print(f"Result: {result}")
    
    time.sleep(2)
    print("\n--- After Event ---")
    check_db()
    
    # Check final status
    details = get_instance(iid)
    if details:
        final_status = details.get('instance', {}).get('status')
        print(f"\nFinal status: {final_status}")

if __name__ == "__main__":
    main()
