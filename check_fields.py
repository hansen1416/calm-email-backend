#!/usr/bin/env python3
"""Quick check for database fields"""

import sys
sys.path.insert(0, '.')

from app import app
from models import db
from sqlalchemy import text

with app.app_context():
    # Check NodeExecution
    print("=== NodeExecution resumed_by_event_id ===")
    result = db.session.execute(
        text('SELECT id, instance_id, node_id, resumed_by_event_id FROM node_execution ORDER BY id DESC LIMIT 5')
    ).fetchall()
    for row in result:
        print(f"  id={row[0]}, instance_id={row[1]}, node_id={row[2]}, resumed_by_event_id={row[3]}")
    
    print()
    print("=== EmailLog source_event_id ===")
    result2 = db.session.execute(
        text('SELECT id, instance_id, source_event_id, message_id FROM email_log ORDER BY id DESC LIMIT 5')
    ).fetchall()
    for row in result2:
        print(f"  id={row[0]}, instance_id={row[1]}, source_event_id={row[2]}, message_id={row[3]}")
