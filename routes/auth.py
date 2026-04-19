from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import (
    create_access_token, create_refresh_token, jwt_required, get_jwt_identity,
    set_access_cookies, set_refresh_cookies, unset_jwt_cookies
)
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
        current_app.logger.warning(f"Failed login attempt for username: {username}")
        return jsonify(msg='用户名或密码错误'), 401
    
    # 创建访问令牌和刷新令牌
    access_token = create_access_token(identity=str(user.id), fresh=True)
    refresh_token = create_refresh_token(identity=str(user.id))
    
    current_app.logger.info(f"User {username} logged in successfully")
    
    return jsonify(
        access_token=access_token,
        refresh_token=refresh_token,
        username=user.username
    ), 200


@auth_bp.route('/refresh', methods=['POST'])
@jwt_required(refresh=True)
def refresh():
    """
    刷新访问令牌
    使用刷新令牌获取新的访问令牌
    """
    user_id = get_jwt_identity()
    new_token = create_access_token(identity=user_id, fresh=False)
    return jsonify(access_token=new_token), 200


@auth_bp.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    """
    登出
    客户端应清除存储的令牌
    """
    user_id = get_jwt_identity()
    current_app.logger.info(f"User {user_id} logged out")
    return jsonify(msg='登出成功'), 200

@auth_bp.route('/me', methods=['GET'])
@jwt_required()
def me():
    user = User.query.get(int(get_jwt_identity()))
    return jsonify(id=user.id, username=user.username, email=user.email), 200
