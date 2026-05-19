#!/usr/bin/env python3
"""测试延时任务执行后的字段记录"""

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

def simulate_sns_webhook(msg_id, email, event_type="delivery"):
    headers = {"Authorization": f"Bearer {TOKEN}"}
    
    sns_message = {
        "eventType": event_type,
        "mail": {
            "messageId": msg_id,
            "commonHeaders": {"to": [email]},
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

def get_scheduled_jobs():
    headers = {"Authorization": f"Bearer {TOKEN}"}
    resp = requests.get(f"{BASE_URL}/api/scheduler/jobs", headers=headers)
    if resp.status_code == 200:
        return resp.json()
    return None

def check_db(instance_id=None):
    from app import app
    from models import db
    from sqlalchemy import text
    with app.app_context():
        print("\n=== NodeExecution ===")
        if instance_id:
            r = db.session.execute(text(
                f'SELECT id, instance_id, node_id, node_type, result, resumed_by_event_id, event_data '
                f'FROM node_execution WHERE instance_id = {instance_id} ORDER BY id'
            )).fetchall()
        else:
            r = db.session.execute(text(
                'SELECT id, instance_id, node_id, node_type, result, resumed_by_event_id, event_data '
                'FROM node_execution ORDER BY id DESC LIMIT 10'
            )).fetchall()
        for row in r:
            print(f"  id={row[0]}, inst={row[1]}, node={row[2]}, type={row[3]}, result={row[4]}, event_id={row[5]}, has_data={row[6] is not None}")
        
        print("\n=== EmailLog ===")
        if instance_id:
            r = db.session.execute(text(
                f'SELECT id, instance_id, recipient_email, source_event_id, message_id, sender_binding_id, sender_email_type, reply_to_email '
                f'FROM email_log WHERE instance_id = {instance_id} ORDER BY id'
            )).fetchall()
        else:
            r = db.session.execute(text(
                'SELECT id, instance_id, recipient_email, source_event_id, message_id, sender_binding_id, sender_email_type, reply_to_email '
                'FROM email_log ORDER BY id DESC LIMIT 10'
            )).fetchall()
        for row in r:
            print(f"  id={row[0]}, inst={row[1]}, email={row[2]}, src_evt={row[3]}, msg_id={row[4][:20] if row[4] else None}, bind_id={row[5]}, type={row[6]}, reply={row[7]}")
        
        print("\n=== EmailEvent ===")
        if instance_id:
            r = db.session.execute(text(
                f'SELECT id, instance_id, event_type, message_id, source_email_log_id FROM email_event WHERE instance_id = {instance_id}'
            )).fetchall()
        else:
            r = db.session.execute(text(
                'SELECT id, instance_id, event_type, message_id, source_email_log_id FROM email_event ORDER BY id DESC LIMIT 5'
            )).fetchall()
        for row in r:
            print(f"  id={row[0]}, inst={row[1]}, type={row[2]}, msg_id={row[3][:20] if row[3] else None}, log_id={row[4]}")
        
        print("\n=== WorkflowInstance ===")
        r = db.session.execute(text(
            'SELECT id, status, message_id, recipient_email FROM workflow_instance ORDER BY id DESC LIMIT 5'
        )).fetchall()
        for row in r:
            print(f"  id={row[0]}, status={row[1]}, msg_id={row[2][:20] if row[2] else None}, email={row[3]}")

def wait_for_scheduler(timeout=120):
    """等待调度器执行任务"""
    print(f"\nWaiting up to {timeout}s for scheduler to execute delayed task...")
    start = time.time()
    while time.time() - start < timeout:
        jobs = get_scheduled_jobs()
        if jobs:
            pending = [j for j in jobs.get('jobs', []) if j.get('status') == 'pending']
            print(f"  Pending jobs: {len(pending)}")
            if pending:
                for j in pending:
                    print(f"    - {j.get('id')}, next_run: {j.get('next_run_time')}")
        
        # Check instance status
        time.sleep(5)
    print("Timeout waiting for scheduler")

def main():
    print("="*60)
    print("Test Delay Task Field Recording")
    print("="*60)
    
    if not get_token():
        return
    
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
    
    # 模拟SNS事件
    print("\n--- Simulate SNS Event ---")
    result = simulate_sns_webhook(msg_id, email, "delivery")
    print(f"Result: {result}")
    
    time.sleep(2)
    
    # 检查延时任务是否已调度
    print("\n--- Check Scheduled Jobs ---")
    jobs = get_scheduled_jobs()
    if jobs:
        print(f"Total jobs: {jobs.get('total', 0)}")
        for j in jobs.get('jobs', []):
            print(f"  {j.get('id')}: status={j.get('status')}, next={j.get('next_run_time')}")
    
    # 检查DB状态
    print(f"\n--- After Event (Instance {iid}) ---")
    check_db(iid)
    
    # 获取实例当前状态
    details = get_instance(iid)
    if details:
        status = details.get('instance', {}).get('status')
        print(f"\nInstance status: {status}")
        
        if status == 'delayed':
            print("\n--- Waiting for delay task to complete ---")
            print("NOTE: Delay task should execute node-3 (email node)")
            print("After execution, check:")
            print("  - NodeExecution for node-3 should have resumed_by_event_id = event.id")
            print("  - EmailLog for node-3 should have source_event_id = event.id")
            print("\nThe delay is 1 minute. You can:")
            print("  1. Wait for scheduler to execute (check logs)")
            print("  2. Or manually trigger by calling the delay task")

if __name__ == "__main__":
    main()
