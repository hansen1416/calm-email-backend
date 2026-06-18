from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, ManualTask, WorkflowInstance
from datetime import datetime

tasks_bp = Blueprint('tasks', __name__)


@tasks_bp.route('', methods=['GET'])
@jwt_required()
def list_tasks():
    uid = int(get_jwt_identity())
    status = request.args.get('status', '')
    q = ManualTask.query.filter_by(user_id=uid)
    if status:
        q = q.filter_by(status=status)
    tasks = q.order_by(ManualTask.created_at.desc()).all()
    return jsonify([t.to_dict() for t in tasks]), 200


@tasks_bp.route('/<int:tid>/complete', methods=['POST'])
@jwt_required()
def complete_task(tid):
    uid = int(get_jwt_identity())
    t = ManualTask.query.filter_by(id=tid, user_id=uid).first()
    if not t:
        return jsonify(msg='任务不存在'), 404
    if t.status != 'pending':
        return jsonify(msg='任务已完成或已取消'), 400

    data = request.get_json() or {}
    t.status = 'completed'
    t.result = data.get('result', '')
    t.completed_at = datetime.utcnow()
    t.completed_by = uid

    # 恢复关联的工作流实例
    if t.instance_id:
        inst = WorkflowInstance.query.get(t.instance_id)
        if inst and inst.status == 'waiting_manual_action':
            inst.status = 'running'
            inst.waiting_event_type = None
            inst.waiting_since = None

    db.session.commit()
    return jsonify(t.to_dict()), 200


@tasks_bp.route('/<int:tid>', methods=['DELETE'])
@jwt_required()
def delete_task(tid):
    uid = int(get_jwt_identity())
    t = ManualTask.query.filter_by(id=tid, user_id=uid).first()
    if not t:
        return jsonify(msg='任务不存在'), 404
    db.session.delete(t)
    db.session.commit()
    return jsonify(msg='删除成功'), 200