from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from models import db, User

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    email = data.get('email', '').strip()
    if not username or not password:
        return jsonify(msg='用户名和密码不能为空'), 400
    if User.query.filter_by(username=username).first():
        return jsonify(msg='用户名已存在'), 400
    user = User(username=username, email=email)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return jsonify(msg='注册成功'), 201

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        return jsonify(msg='用户名或密码错误'), 401
    token = create_access_token(identity=str(user.id))
    return jsonify(token=token, username=user.username), 200

@auth_bp.route('/me', methods=['GET'])
@jwt_required()
def me():
    user = User.query.get(int(get_jwt_identity()))
    return jsonify(id=user.id, username=user.username, email=user.email), 200
