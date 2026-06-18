"""Add avatar column to user table if missing"""
from app import create_app
from models import db
import sqlalchemy as sa

app = create_app()
with app.app_context():
    inspector = sa.inspect(db.engine)
    columns = [c['name'] for c in inspector.get_columns('user')]
    print('Current columns:', columns)
    if 'avatar' not in columns:
        db.session.execute(
            sa.text('ALTER TABLE user ADD COLUMN avatar VARCHAR(50) DEFAULT "avatar-1"')
        )
        db.session.commit()
        print('✅ Added avatar column')
    else:
        print('✅ avatar column already exists')
