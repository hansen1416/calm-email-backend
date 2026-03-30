from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, ContactGroup, Contact

groups_bp = Blueprint('groups', __name__)

def group_to_dict(g):
    return dict(id=g.id, name=g.name, description=g.description,
                contact_count=len(g.contacts),
                contacts=[dict(id=c.id, name=c.name, email=c.email) for c in g.contacts],
                created_at=g.created_at.strftime('%Y-%m-%d %H:%M:%S'))

@groups_bp.route('', methods=['GET'])
@jwt_required()
def list_groups():
    uid = int(get_jwt_identity())
    groups = ContactGroup.query.filter_by(user_id=uid).order_by(ContactGroup.created_at.desc()).all()
    return jsonify([group_to_dict(g) for g in groups]), 200

@groups_bp.route('', methods=['POST'])
@jwt_required()
def create_group():
    uid = int(get_jwt_identity())
    data = request.get_json()
    if not data.get('name'):
        return jsonify(msg='组名不能为空'), 400
    g = ContactGroup(user_id=uid, name=data['name'], description=data.get('description', ''))
    db.session.add(g)
    db.session.commit()
    return jsonify(group_to_dict(g)), 201

@groups_bp.route('/<int:gid>', methods=['PUT'])
@jwt_required()
def update_group(gid):
    uid = int(get_jwt_identity())
    g = ContactGroup.query.filter_by(id=gid, user_id=uid).first()
    if not g:
        return jsonify(msg='用户组不存在'), 404
    data = request.get_json()
    g.name = data.get('name', g.name)
    g.description = data.get('description', g.description)
    db.session.commit()
    return jsonify(group_to_dict(g)), 200

@groups_bp.route('/<int:gid>', methods=['DELETE'])
@jwt_required()
def delete_group(gid):
    uid = int(get_jwt_identity())
    g = ContactGroup.query.filter_by(id=gid, user_id=uid).first()
    if not g:
        return jsonify(msg='用户组不存在'), 404
    db.session.delete(g)
    db.session.commit()
    return jsonify(msg='删除成功'), 200

@groups_bp.route('/<int:gid>/members', methods=['POST'])
@jwt_required()
def add_members(gid):
    uid = int(get_jwt_identity())
    g = ContactGroup.query.filter_by(id=gid, user_id=uid).first()
    if not g:
        return jsonify(msg='用户组不存在'), 404
    data = request.get_json()
    contact_ids = data.get('contact_ids', [])
    contacts = Contact.query.filter(Contact.id.in_(contact_ids), Contact.user_id == uid).all()
    for c in contacts:
        if c not in g.contacts:
            g.contacts.append(c)
    db.session.commit()
    return jsonify(group_to_dict(g)), 200

@groups_bp.route('/<int:gid>/members', methods=['DELETE'])
@jwt_required()
def remove_members(gid):
    uid = int(get_jwt_identity())
    g = ContactGroup.query.filter_by(id=gid, user_id=uid).first()
    if not g:
        return jsonify(msg='用户组不存在'), 404
    data = request.get_json()
    contact_ids = data.get('contact_ids', [])
    g.contacts = [c for c in g.contacts if c.id not in contact_ids]
    db.session.commit()
    return jsonify(group_to_dict(g)), 200
