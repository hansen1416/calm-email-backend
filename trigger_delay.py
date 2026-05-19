#!/usr/bin/env python3
"""手动触发延时任务并验证字段"""

import sys
sys.path.insert(0, '.')

from app import app
from models import db, WorkflowInstance
from services.scheduler import execute_delayed_node
from sqlalchemy import text

def check_instance_fields(instance_id):
    """检查指定实例的字段"""
    with app.app_context():
        print(f"\n=== Instance {instance_id} ===")
        
        # 检查 NodeExecution
        print("\nNodeExecution:")
        r = db.session.execute(text(
            f'SELECT id, node_id, node_type, result, resumed_by_event_id, '
            f'CASE WHEN event_data IS NOT NULL THEN 1 ELSE 0 END as has_data '
            f'FROM node_execution WHERE instance_id = {instance_id} ORDER BY id'
        )).fetchall()
        for row in r:
            print(f"  id={row[0]}, node={row[1]}, type={row[2]}, result={row[3]}, event_id={row[4]}, has_data={row[5]}")
        
        # 检查 EmailLog
        print("\nEmailLog:")
        r = db.session.execute(text(
            f'SELECT id, recipient_email, source_event_id, message_id, sender_binding_id, sender_email_type '
            f'FROM email_log WHERE instance_id = {instance_id} ORDER BY id'
        )).fetchall()
        for row in r:
            print(f"  id={row[0]}, email={row[1]}, src_evt={row[2]}, msg_id={row[3][:20] if row[3] else None}, bind={row[4]}, type={row[5]}")
        
        # 检查 EmailEvent
        print("\nEmailEvent:")
        r = db.session.execute(text(
            f'SELECT id, event_type, message_id, source_email_log_id '
            f'FROM email_event WHERE instance_id = {instance_id}'
        )).fetchall()
        for row in r:
            print(f"  id={row[0]}, type={row[1]}, msg_id={row[2][:20] if row[2] else None}, log_id={row[3]}")
        
        # 检查实例状态
        r = db.session.execute(text(
            f'SELECT status, message_id FROM workflow_instance WHERE id = {instance_id}'
        )).fetchone()
        if r:
            print(f"\nInstance status: {r[0]}, msg_id: {r[1][:20] if r[1] else None}")

def trigger_delay_task(instance_id):
    """手动触发延时任务"""
    with app.app_context():
        instance = WorkflowInstance.query.get(instance_id)
        if not instance:
            print(f"Instance {instance_id} not found")
            return False
        
        if instance.status != 'delayed':
            print(f"Instance {instance_id} status is {instance.status}, expected 'delayed'")
            return False
        
        # 获取工作流
        from models import Workflow
        workflow = Workflow.query.get(instance.workflow_id)
        if not workflow:
            print(f"Workflow {instance.workflow_id} not found")
            return False
        
        # 获取节点数据
        import json
        flow = json.loads(workflow.flow_data)
        nodes = flow.get('nodes', [])
        
        # 找到延时节点后的邮件节点 (node-3)
        target_node = None
        for node in nodes:
            if node.get('id') == 'node-3':
                target_node = node
                break
        
        if not target_node:
            print("Target node (node-3) not found")
            return False
        
        print(f"Triggering delay task for instance {instance_id}, node {target_node.get('id')}")
        
        # 手动执行延时任务
        execute_delayed_node(
            workflow_id=instance.workflow_id,
            instance_id=instance_id,
            node_data=target_node,
            recipient_email=instance.recipient_email,
            mock_send=True
        )
        
        return True

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Trigger delay task and check fields')
    parser.add_argument('--instance', type=int, default=6, help='Instance ID to trigger')
    parser.add_argument('--check-only', action='store_true', help='Only check fields, do not trigger')
    args = parser.parse_args()
    
    if args.check_only:
        check_instance_fields(args.instance)
    else:
        print(f"Triggering delay task for instance {args.instance}...")
        if trigger_delay_task(args.instance):
            print("\nDelay task triggered successfully!")
            check_instance_fields(args.instance)
        else:
            print("\nFailed to trigger delay task")
