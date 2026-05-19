#!/usr/bin/env python3
"""直接检查数据库中的字段值"""

import sys
sys.path.insert(0, '.')

from app import app
from models import db
from sqlalchemy import text

def check_all():
    with app.app_context():
        print("="*60)
        print("Database Field Check")
        print("="*60)
        
        print("\n=== NodeExecution ===")
        r = db.session.execute(text(
            'SELECT id, instance_id, node_id, node_type, result, resumed_by_event_id, '
            'CASE WHEN event_data IS NOT NULL THEN 1 ELSE 0 END as has_event_data '
            'FROM node_execution ORDER BY id DESC LIMIT 10'
        )).fetchall()
        for row in r:
            print(f"  id={row[0]}, inst={row[1]}, node={row[2]}, type={row[3]}, result={row[4]}, resumed_by={row[5]}, has_data={row[6]}")
        
        print("\n=== EmailLog ===")
        r = db.session.execute(text(
            'SELECT id, instance_id, recipient_email, source_event_id, message_id, '
            'sender_binding_id, sender_email_type, reply_to_email '
            'FROM email_log ORDER BY id DESC LIMIT 10'
        )).fetchall()
        for row in r:
            print(f"  id={row[0]}, inst={row[1]}, email={row[2]}, src_evt={row[3]}, msg_id={row[4][:20] if row[4] else None}, bind_id={row[5]}, type={row[6]}, reply={row[7]}")
        
        print("\n=== EmailEvent ===")
        r = db.session.execute(text(
            'SELECT id, instance_id, event_type, message_id, source_email_log_id '
            'FROM email_event ORDER BY id DESC LIMIT 5'
        )).fetchall()
        for row in r:
            print(f"  id={row[0]}, inst={row[1]}, type={row[2]}, msg_id={row[3][:20] if row[3] else None}, log_id={row[4]}")
        
        print("\n=== WorkflowInstance ===")
        r = db.session.execute(text(
            'SELECT id, status, message_id, recipient_email, workflow_id '
            'FROM workflow_instance ORDER BY id DESC LIMIT 5'
        )).fetchall()
        for row in r:
            print(f"  id={row[0]}, status={row[1]}, msg_id={row[2][:20] if row[2] else None}, email={row[3]}, wf_id={row[4]}")

if __name__ == "__main__":
    check_all()
