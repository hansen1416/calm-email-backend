"""
工作流实例管理 API
提供 WorkflowInstance 的 CRUD 和状态管理
"""
import json
from datetime import datetime
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Workflow, WorkflowInstance, EmailLog, EmailEvent

instance_bp = Blueprint('instance', __name__)


def instance_to_dict(instance):
    """将 WorkflowInstance 转换为字典"""
    return {
        'id': instance.id,
        'workflow_id': instance.workflow_id,
        'workflow_name': instance.workflow.name if instance.workflow else None,
        'recipient_email': instance.recipient_email,
        'message_id': instance.message_id,
        'status': instance.status,
        'current_node_id': instance.current_node_id,
        'waiting_event_type': instance.waiting_event_type,
        'waiting_conditions': instance.waiting_conditions,
        'waiting_since': instance.waiting_since.strftime('%Y-%m-%d %H:%M:%S') if instance.waiting_since else None,
        'context': instance.context,
        'created_at': instance.created_at.strftime('%Y-%m-%d %H:%M:%S') if instance.created_at else None,
        'updated_at': instance.updated_at.strftime('%Y-%m-%d %H:%M:%S') if instance.updated_at else None,
        'completed_at': instance.completed_at.strftime('%Y-%m-%d %H:%M:%S') if instance.completed_at else None
    }


@instance_bp.route('/workflow/<int:wid>/instances', methods=['GET'])
@jwt_required()
def list_workflow_instances(wid):
    """获取工作流的所有实例"""
    uid = int(get_jwt_identity())
    
    # 检查工作流权限
    workflow = Workflow.query.filter_by(id=wid, user_id=uid).first()
    if not workflow:
        return jsonify(msg='工作流不存在'), 404
    
    # 查询参数
    status = request.args.get('status')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    query = WorkflowInstance.query.filter_by(workflow_id=wid, user_id=uid)
    
    if status:
        query = query.filter(WorkflowInstance.status == status)
    
    pagination = query.order_by(WorkflowInstance.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    return jsonify({
        'instances': [instance_to_dict(i) for i in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page
    }), 200


@instance_bp.route('/instance/<int:iid>', methods=['GET'])
@jwt_required()
def get_instance(iid):
    """获取单个实例详情"""
    from models import NodeExecution
    uid = int(get_jwt_identity())

    instance = WorkflowInstance.query.filter_by(id=iid, user_id=uid).first()
    if not instance:
        return jsonify(msg='实例不存在'), 404

    # 获取执行历史
    logs = EmailLog.query.filter_by(instance_id=iid).order_by(EmailLog.sent_at.desc()).all()
    events = EmailEvent.query.filter_by(instance_id=iid).order_by(EmailEvent.created_at.desc()).all()
    node_execs = NodeExecution.query.filter_by(instance_id=iid).order_by(NodeExecution.executed_at.desc(), NodeExecution.id.desc()).all()

    return jsonify({
        'instance': instance_to_dict(instance),
        'email_logs': [{
            'id': log.id,
            'subject': log.subject,
            'recipient_email': log.recipient_email,
            'status': log.status,
            'message_id': log.message_id,
            'sent_at': log.sent_at.strftime('%Y-%m-%d %H:%M:%S') if log.sent_at else None
        } for log in logs],
        'events': [{
            'id': event.id,
            'event_type': event.event_type,
            'recipient_email': event.recipient_email,
            'event_data': event.event_data,
            'created_at': event.created_at.strftime('%Y-%m-%d %H:%M:%S') if event.created_at else None
        } for event in events],
        'node_executions': [{
            'id': exec.id,
            'node_id': exec.node_id,
            'node_type': exec.node_type,
            'node_label': exec.node_label,
            'result': exec.result,
            'input_data': exec.input_data,
            'output_data': exec.output_data,
            'event_data': exec.event_data,
            'conditions_met': exec.conditions_met,
            'error_message': exec.error_message,
            'duration_ms': exec.duration_ms,
            'executed_at': exec.executed_at.strftime('%Y-%m-%d %H:%M:%S') if exec.executed_at else None,
            'completed_at': exec.completed_at.strftime('%Y-%m-%d %H:%M:%S') if exec.completed_at else None
        } for exec in node_execs]
    }), 200


@instance_bp.route('/user/instances', methods=['GET'])
@jwt_required()
def list_user_instances():
    """获取当前用户的所有实例（跨工作流）"""
    uid = int(get_jwt_identity())
    
    status = request.args.get('status')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    query = WorkflowInstance.query.filter_by(user_id=uid)
    
    if status:
        query = query.filter(WorkflowInstance.status == status)
    
    pagination = query.order_by(WorkflowInstance.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    result = []
    for i in pagination.items:
        data = instance_to_dict(i)
        data['workflow_name'] = i.workflow.name if i.workflow else 'Unknown'
        result.append(data)
    
    return jsonify({
        'instances': result,
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page
    }), 200


@instance_bp.route('/instance/<int:iid>/cancel', methods=['POST'])
@jwt_required()
def cancel_instance(iid):
    """取消等待中的实例"""
    from services.scheduler import cancel_scheduled_job

    uid = int(get_jwt_identity())

    instance = WorkflowInstance.query.filter_by(id=iid, user_id=uid).first()
    if not instance:
        return jsonify(msg='实例不存在'), 404

    # 只有等待状态的实例可以取消
    if instance.status not in ['waiting_event', 'delayed', 'pending']:
        return jsonify(msg=f'实例当前状态为 {instance.status}，无法取消'), 400

    # 如果有延时节点的调度任务，取消它
    if instance.status == 'delayed' and instance.context:
        job_id = instance.context.get('scheduled_job_id')
        if job_id:
            cancel_scheduled_job(job_id)

    instance.status = 'cancelled'
    instance.completed_at = datetime.utcnow()
    db.session.commit()

    return jsonify(msg='实例已取消', instance=instance_to_dict(instance)), 200


@instance_bp.route('/instance/<int:iid>/logs', methods=['GET'])
@jwt_required()
def get_instance_logs(iid):
    """获取实例的执行日志"""
    uid = int(get_jwt_identity())
    
    instance = WorkflowInstance.query.filter_by(id=iid, user_id=uid).first()
    if not instance:
        return jsonify(msg='实例不存在'), 404
    
    logs = EmailLog.query.filter_by(instance_id=iid).order_by(EmailLog.sent_at.desc()).all()
    
    return jsonify({
        'logs': [{
            'id': log.id,
            'node_id': log.node_id,
            'subject': log.subject,
            'recipient_email': log.recipient_email,
            'status': log.status,
            'message_id': log.message_id,
            'sent_at': log.sent_at.strftime('%Y-%m-%d %H:%M:%S') if log.sent_at else None
        } for log in logs]
    }), 200
