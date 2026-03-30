from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Contact

contacts_bp = Blueprint('contacts', __name__)

def contact_to_dict(c):
    return dict(id=c.id, name=c.name, email=c.email, phone=c.phone,
                company=c.company, notes=c.notes,
                groups=[g.id for g in c.groups],
                created_at=c.created_at.strftime('%Y-%m-%d %H:%M:%S'))

@contacts_bp.route('', methods=['GET'])
@jwt_required()
def list_contacts():
    uid = int(get_jwt_identity())
    keyword = request.args.get('keyword', '')
    q = Contact.query.filter_by(user_id=uid)
    if keyword:
        q = q.filter(Contact.name.like(f'%{keyword}%') | Contact.email.like(f'%{keyword}%'))
    contacts = q.order_by(Contact.created_at.desc()).all()
    return jsonify([contact_to_dict(c) for c in contacts]), 200

@contacts_bp.route('', methods=['POST'])
@jwt_required()
def create_contact():
    uid = int(get_jwt_identity())
    data = request.get_json()
    if not data.get('name') or not data.get('email'):
        return jsonify(msg='姓名和邮箱不能为空'), 400
    c = Contact(user_id=uid, name=data['name'], email=data['email'],
                phone=data.get('phone', ''), company=data.get('company', ''),
                notes=data.get('notes', ''))
    db.session.add(c)
    db.session.commit()
    return jsonify(contact_to_dict(c)), 201

@contacts_bp.route('/<int:cid>', methods=['PUT'])
@jwt_required()
def update_contact(cid):
    uid = int(get_jwt_identity())
    c = Contact.query.filter_by(id=cid, user_id=uid).first()
    if not c:
        return jsonify(msg='联系人不存在'), 404
    data = request.get_json()
    c.name = data.get('name', c.name)
    c.email = data.get('email', c.email)
    c.phone = data.get('phone', c.phone)
    c.company = data.get('company', c.company)
    c.notes = data.get('notes', c.notes)
    db.session.commit()
    return jsonify(contact_to_dict(c)), 200

@contacts_bp.route('/<int:cid>', methods=['DELETE'])
@jwt_required()
def delete_contact(cid):
    uid = int(get_jwt_identity())
    c = Contact.query.filter_by(id=cid, user_id=uid).first()
    if not c:
        return jsonify(msg='联系人不存在'), 404
    db.session.delete(c)
    db.session.commit()
    return jsonify(msg='删除成功'), 200
