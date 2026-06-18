from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Contact

contacts_bp = Blueprint('contacts', __name__)

def contact_to_dict(c):
    d = dict(id=c.id, name=c.name, email=c.email, phone=c.phone,
             company=c.company, notes=c.notes,
             groups=c.get_group_ids(),
             created_at=c.created_at.strftime('%Y-%m-%d %H:%M:%S'))
    if c.custom_fields:
        d['custom_fields'] = c.custom_fields
    return d

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
                notes=data.get('notes', ''),
                custom_fields=data.get('custom_fields'))
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
    if 'custom_fields' in data:
        c.custom_fields = data['custom_fields']
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

@contacts_bp.route('/import', methods=['POST'])
@jwt_required()
def import_contacts():
    uid = int(get_jwt_identity())
    if 'file' not in request.files:
        return jsonify(msg='请上传CSV文件'), 400
    file = request.files['file']
    mapping = request.form.get('mapping', '{}')
    dedup_strategy = request.form.get('dedup_strategy', 'skip')
    try:
        import json, csv, io
        mapping = json.loads(mapping) if isinstance(mapping, str) else mapping
        content = file.read().decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(content))
        if not reader.fieldnames:
            return jsonify(msg='CSV文件为空或格式错误'), 400
        total = 0
        imported = 0
        skipped = 0
        updated = 0
        errors = []
        for row in reader:
            total += 1
            vals = [v for v in row.values() if v and v.strip()]
            if not vals:
                continue
            contact_data = {'user_id': uid,
                           'name': '', 'email': '', 'phone': '',
                           'company': '', 'notes': ''}
            for csv_col, db_field in mapping.items():
                if csv_col not in row or not db_field:
                    continue
                val = row[csv_col].strip() if row[csv_col] else ''
                if db_field == '_skip' or not val:
                    continue
                if db_field.startswith('custom:'):
                    if 'custom_fields' not in contact_data:
                        contact_data['custom_fields'] = {}
                    contact_data['custom_fields'][db_field[7:]] = val
                else:
                    contact_data[db_field] = val
            email = contact_data.get('email', '').strip()
            if not email:
                errors.append({'row': total, 'msg': 'email为空'})
                continue
            existing = Contact.query.filter_by(user_id=uid, email=email).first()
            if existing:
                if dedup_strategy == 'skip':
                    skipped += 1
                    continue
                elif dedup_strategy == 'update':
                    for key, val in contact_data.items():
                        if key in ('user_id', 'email'):
                            continue
                        if key == 'custom_fields' and val:
                            if existing.custom_fields:
                                existing.custom_fields = {**existing.custom_fields, **val}
                            else:
                                existing.custom_fields = val
                        elif val is not None:
                            setattr(existing, key, val)
                    updated += 1
                else:
                    c = Contact(**{k: v for k, v in contact_data.items() if k != 'user_id'})
                    c.user_id = uid
                    db.session.add(c)
                    imported += 1
            else:
                c = Contact(**{k: v for k, v in contact_data.items() if k != 'user_id'})
                c.user_id = uid
                db.session.add(c)
                imported += 1
        db.session.commit()
        return jsonify(dict(total=total, imported=imported, skipped=skipped,
                           updated=updated, errors=errors)), 200
    except Exception as e:
        db.session.rollback()
        return jsonify(msg=f'导入失败: {str(e)}'), 500