from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, EmailTemplate

templates_bp = Blueprint('templates', __name__)

def tpl_to_dict(t):
    return dict(id=t.id, name=t.name, subject=t.subject, body=t.body,
                created_at=t.created_at.strftime('%Y-%m-%d %H:%M:%S'))

@templates_bp.route('', methods=['GET'])
@jwt_required()
def list_templates():
    uid = int(get_jwt_identity())
    tpls = EmailTemplate.query.filter_by(user_id=uid).order_by(EmailTemplate.created_at.desc()).all()
    return jsonify([tpl_to_dict(t) for t in tpls]), 200

@templates_bp.route('', methods=['POST'])
@jwt_required()
def create_template():
    uid = int(get_jwt_identity())
    data = request.get_json()
    if not data.get('name') or not data.get('subject') or not data.get('body'):
        return jsonify(msg='模板名称、主题和内容不能为空'), 400
    t = EmailTemplate(user_id=uid, name=data['name'], subject=data['subject'], body=data['body'])
    db.session.add(t)
    db.session.commit()
    return jsonify(tpl_to_dict(t)), 201

@templates_bp.route('/<int:tid>', methods=['PUT'])
@jwt_required()
def update_template(tid):
    uid = int(get_jwt_identity())
    t = EmailTemplate.query.filter_by(id=tid, user_id=uid).first()
    if not t:
        return jsonify(msg='模板不存在'), 404
    data = request.get_json()
    t.name = data.get('name', t.name)
    t.subject = data.get('subject', t.subject)
    t.body = data.get('body', t.body)
    db.session.commit()
    return jsonify(tpl_to_dict(t)), 200

@templates_bp.route('/<int:tid>', methods=['DELETE'])
@jwt_required()
def delete_template(tid):
    uid = int(get_jwt_identity())
    t = EmailTemplate.query.filter_by(id=tid, user_id=uid).first()
    if not t:
        return jsonify(msg='模板不存在'), 404
    db.session.delete(t)
    db.session.commit()
    return jsonify(msg='删除成功'), 200
