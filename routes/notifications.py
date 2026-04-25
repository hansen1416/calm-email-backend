"""
系统通知 API
M5: 通知中心 - 用于回复通知等系统消息
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Notification
from datetime import datetime

notifications_bp = Blueprint('notifications', __name__)


@notifications_bp.route('/notifications', methods=['GET'])
@jwt_required()
def list_notifications():
    """
    获取用户的通知列表
    支持分页和筛选
    """
    uid = int(get_jwt_identity())
    
    # 分页参数
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    unread_only = request.args.get('unread_only', 'false').lower() == 'true'
    
    # 限制每页数量
    if per_page > 100:
        per_page = 100
    
    # 构建查询
    query = Notification.query.filter_by(user_id=uid)
    
    if unread_only:
        query = query.filter_by(is_read=False)
    
    # 按时间倒序
    query = query.order_by(Notification.created_at.desc())
    
    # 分页
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
    result = []
    for n in pagination.items:
        data = {
            'id': n.id,
            'type': n.type,
            'title': n.title,
            'content': n.content,
            'is_read': n.is_read,
            'created_at': n.created_at.isoformat() if n.created_at else None,
            'related_data': n.related_data
        }
        result.append(data)
    
    # 统计未读数量
    unread_count = Notification.query.filter_by(user_id=uid, is_read=False).count()
    
    return jsonify({
        'notifications': result,
        'unread_count': unread_count,
        'pagination': {
            'page': pagination.page,
            'per_page': pagination.per_page,
            'total': pagination.total,
            'pages': pagination.pages,
            'has_next': pagination.has_next,
            'has_prev': pagination.has_prev
        }
    }), 200


@notifications_bp.route('/notifications/<int:notification_id>/read', methods=['PUT'])
@jwt_required()
def mark_notification_read(notification_id):
    """标记通知为已读"""
    uid = int(get_jwt_identity())
    
    notification = Notification.query.filter_by(
        id=notification_id,
        user_id=uid
    ).first()
    
    if not notification:
        return jsonify(msg='通知不存在'), 404
    
    notification.is_read = True
    notification.read_at = datetime.utcnow()
    db.session.commit()
    
    return jsonify({
        'msg': '已标记为已读',
        'id': notification_id
    }), 200


@notifications_bp.route('/notifications/read-all', methods=['PUT'])
@jwt_required()
def mark_all_notifications_read():
    """标记所有通知为已读"""
    uid = int(get_jwt_identity())
    
    Notification.query.filter_by(
        user_id=uid,
        is_read=False
    ).update({
        'is_read': True,
        'read_at': datetime.utcnow()
    })
    
    db.session.commit()
    
    return jsonify({
        'msg': '所有通知已标记为已读'
    }), 200


@notifications_bp.route('/notifications/<int:notification_id>', methods=['DELETE'])
@jwt_required()
def delete_notification(notification_id):
    """删除通知"""
    uid = int(get_jwt_identity())
    
    notification = Notification.query.filter_by(
        id=notification_id,
        user_id=uid
    ).first()
    
    if not notification:
        return jsonify(msg='通知不存在'), 404
    
    db.session.delete(notification)
    db.session.commit()
    
    return jsonify({
        'msg': '通知已删除',
        'id': notification_id
    }), 200


@notifications_bp.route('/notifications/unread-count', methods=['GET'])
@jwt_required()
def get_unread_count():
    """获取未读通知数量"""
    uid = int(get_jwt_identity())
    
    count = Notification.query.filter_by(
        user_id=uid,
        is_read=False
    ).count()
    
    return jsonify({
        'unread_count': count
    }), 200
