from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Contact

segments_bp = Blueprint('segments', __name__)

from datetime import datetime

class Segment(db.Model):
    __tablename__ = 'segment'
    __table_args__ = (
        db.Index('idx_segment_user_id', 'user_id'),
        {'comment': '动态分段表'}
    )
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    rules = db.Column(db.JSON, nullable=False)
    match_type = db.Column(db.String(10), default='all')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Segment {self.name}>'

def seg_to_dict(s):
    return dict(id=s.id, name=s.name, description=s.description,
                rules=s.rules, match_type=s.match_type,
                created_at=s.created_at.strftime('%Y-%m-%d %H:%M:%S'))

def contact_to_dict(c):
    d = dict(id=c.id, name=c.name, email=c.email, phone=c.phone,
             company=c.company, notes=c.notes,
             created_at=c.created_at.strftime('%Y-%m-%d %H:%M:%S'))
    return d
def _evaluate_rule(contact, rule):
    field = rule.get('field', '')
    operator = rule.get('operator', 'equals')
    value = rule.get('value', '')
    if field in ('name', 'email', 'phone', 'company', 'notes'):
        field_val = (getattr(contact, field) or '')
    else:
        return False
    field_val = field_val.lower() if field_val else ''
    value = value.lower() if value else ''
    if operator == 'equals':
        return field_val == value
    elif operator == 'not_equals':
        return field_val != value
    elif operator == 'contains':
        return value in field_val
    elif operator == 'not_contains':
        return value not in field_val
    elif operator == 'starts_with':
        return field_val.startswith(value) if value else True
    elif operator == 'ends_with':
        return field_val.endswith(value) if value else True
    elif operator == 'is_empty':
        return not field_val
    elif operator == 'is_not_empty':
        return bool(field_val)
    return False

@segments_bp.route('', methods=['GET'])
@jwt_required()
def list_segments():
    uid = int(get_jwt_identity())
    segs = Segment.query.filter_by(user_id=uid).order_by(Segment.created_at.desc()).all()
    return jsonify([seg_to_dict(s) for s in segs]), 200

@segments_bp.route('', methods=['POST'])
@jwt_required()
def create_segment():
    uid = int(get_jwt_identity())
    data = request.get_json()
    if not data.get('name') or not data.get('rules'):
        return jsonify(msg='分段名称和规则不能为空'), 400
    s = Segment(user_id=uid, name=data['name'],
                description=data.get('description', ''),
                rules=data['rules'],
                match_type=data.get('match_type', 'all'))
    db.session.add(s)
    db.session.commit()
    return jsonify(seg_to_dict(s)), 201

@segments_bp.route('/<int:sid>', methods=['PUT'])
@jwt_required()
def update_segment(sid):
    uid = int(get_jwt_identity())
    s = Segment.query.filter_by(id=sid, user_id=uid).first()
    if not s:
        return jsonify(msg='分段不存在'), 404
    data = request.get_json()
    s.name = data.get('name', s.name)
    s.description = data.get('description', s.description)
    s.rules = data.get('rules', s.rules)
    s.match_type = data.get('match_type', s.match_type)
    db.session.commit()
    return jsonify(seg_to_dict(s)), 200

@segments_bp.route('/<int:sid>', methods=['DELETE'])
@jwt_required()
def delete_segment(sid):
    uid = int(get_jwt_identity())
    s = Segment.query.filter_by(id=sid, user_id=uid).first()
    if not s:
        return jsonify(msg='分段不存在'), 404
    db.session.delete(s)
    db.session.commit()
    return jsonify(msg='删除成功'), 200

@segments_bp.route('/<int:sid>/preview', methods=['POST'])
@jwt_required()
def preview_segment(sid):
    uid = int(get_jwt_identity())
    s = Segment.query.filter_by(id=sid, user_id=uid).first()
    if not s:
        return jsonify(msg='分段不存在'), 404
    contacts = Contact.query.filter_by(user_id=uid).all()
    matched = []
    for c in contacts:
        results = [_evaluate_rule(c, r) for r in s.rules]
        if s.match_type == 'all':
            if all(results):
                matched.append(c.id)
        else:
            if any(results):
                matched.append(c.id)
    sample = [contact_to_dict(c) for c in contacts if c.id in matched[:5]]
    return jsonify(dict(count=len(matched), sample=sample)), 200