import json
import uuid
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Workflow, WorkflowInstance, EmailTemplate, EmailLog, Contact, ContactGroup, NodeExecution
from routes.email import send_email
from services.scheduler import schedule_relative_delay, schedule_absolute_delay

workflow_bp = Blueprint('workflow', __name__)


def wf_to_dict(w):
    return dict(
        id=w.id,
        name=w.name,
        flow_data=json.loads(w.flow_data),
        status=w.status,
        execution_mode=w.execution_mode,
        start_time=w.start_time.strftime('%Y-%m-%dT%H:%M') if w.start_time else None,
        last_executed_at=w.last_executed_at.strftime('%Y-%m-%d %H:%M:%S') if w.last_executed_at else None,
        created_at=w.created_at.strftime('%Y-%m-%d %H:%M:%S')
    )


@workflow_bp.route('', methods=['GET'])
@jwt_required()
def list_workflows():
    uid = int(get_jwt_identity())
    wfs = Workflow.query.filter_by(user_id=uid).order_by(Workflow.created_at.desc()).all()
    return jsonify([wf_to_dict(w) for w in wfs]), 200


@workflow_bp.route('', methods=['POST'])
@jwt_required()
def create_workflow():
    uid = int(get_jwt_identity())
    data = request.get_json()
    if not data.get('name'):
        return jsonify(msg='名称不能为空'), 400

    start_time = None
    if data.get('start_time'):
        try:
            start_time = datetime.fromisoformat(data['start_time'].replace('Z', '+00:00'))
        except:
            start_time = datetime.strptime(data['start_time'], '%Y-%m-%dT%H:%M')

    w = Workflow(
        user_id=uid,
        name=data['name'],
        flow_data=json.dumps(data.get('flow_data', {})),
        status=data.get('status', 'inactive'),
        execution_mode=data.get('execution_mode', 'manual'),
        start_time=start_time
    )
    db.session.add(w)
    db.session.commit()
    return jsonify(wf_to_dict(w)), 201


@workflow_bp.route('/<int:wid>', methods=['PUT'])
@jwt_required()
def update_workflow(wid):
    uid = int(get_jwt_identity())
    w = Workflow.query.filter_by(id=wid, user_id=uid).first()
    if not w:
        return jsonify(msg='工作流不存在'), 404

    data = request.get_json()

    if 'name' in data:
        w.name = data['name']
    if 'status' in data:
        w.status = data['status']
    if 'execution_mode' in data:
        w.execution_mode = data['execution_mode']
    if 'start_time' in data:
        if data['start_time']:
            try:
                w.start_time = datetime.fromisoformat(data['start_time'].replace('Z', '+00:00'))
            except:
                try:
                    w.start_time = datetime.strptime(data['start_time'], '%Y-%m-%dT%H:%M')
                except:
                    w.start_time = None
        else:
            w.start_time = None
    if 'flow_data' in data:
        w.flow_data = json.dumps(data['flow_data'])

    db.session.commit()
    return jsonify(wf_to_dict(w)), 200


@workflow_bp.route('/<int:wid>', methods=['DELETE'])
@jwt_required()
def delete_workflow(wid):
    uid = int(get_jwt_identity())
    w = Workflow.query.filter_by(id=wid, user_id=uid).first()
    if not w:
        return jsonify(msg='工作流不存在'), 404
    db.session.delete(w)
    db.session.commit()
    return jsonify(msg='删除成功'), 200


def evaluate_condition(field, operator, value, event_data):
    """评估条件是否满足"""
    field_value = None
    if field == 'event_type':
        field_value = event_data.get('event_type')
    elif field == 'link_url':
        field_value = event_data.get('link_url') or event_data.get('click', {}).get('link')
    elif field == 'recipient':
        field_value = event_data.get('recipient_email') or event_data.get('mail', {}).get('commonHeaders', {}).get('to', [None])[0]

    if field_value is None:
        return False

    if operator == 'eq':
        return str(field_value) == str(value)
    elif operator == 'neq':
        return str(field_value) != str(value)
    elif operator == 'contains':
        return str(value) in str(field_value)
    elif operator == 'not_contains':
        return str(value) not in str(field_value)
    return False


def execute_node_for_instance(instance, node, node_map, next_map, uid, mock=False, resumed_event_data=None):
    """为单个实例执行节点

    Args:
        instance: WorkflowInstance 对象
        node: 当前节点数据
        node_map: 节点映射
        next_map: 边映射
        uid: 用户ID
        mock: 是否模拟发送
        resumed_event_data: 如果是恢复执行，传入触发的事件数据

    Returns:
        dict: 执行结果 {continue: bool, paused: bool, result: str, output: dict}
    """
    from models import NodeExecution

    node_id = node.get('id')
    data = node.get('data', {})
    node_type = data.get('nodeType', 'email')
    label = data.get('label', '未命名节点')
    start_time = datetime.utcnow()

    # 创建节点执行记录
    node_exec = NodeExecution(
        instance_id=instance.id,
        node_id=node_id,
        node_type=node_type,
        node_label=label,
        result='running',
        input_data=data
    )
    db.session.add(node_exec)
    db.session.commit()

    # 更新实例当前节点
    instance.current_node_id = node_id
    instance.updated_at = datetime.utcnow()

    # 初始化执行历史（如果不存在）
    if not instance.context:
        instance.context = {}
    if 'execution_history' not in instance.context:
        instance.context['execution_history'] = []

    # 记录执行历史
    history_entry = {
        'node_id': node_id,
        'node_type': node_type,
        'node_label': label,
        'executed_at': start_time.isoformat(),
        'input_data': data
    }
    
    if node_type == 'email':
        # 执行邮件节点
        template_id = data.get('template_id')
        contact_ids = data.get('contact_ids', [])
        group_ids = data.get('group_ids', [])
        
        if not template_id:
            return False
        
        tpl = EmailTemplate.query.filter_by(id=template_id, user_id=uid).first()
        if not tpl:
            return False
        
        # 只发送给当前实例对应的收件人
        emails = set()
        if instance.recipient_email:
            emails.add(instance.recipient_email)
        
        # 如果没有特定收件人，使用联系人/群组配置
        if not emails:
            if contact_ids:
                for c in Contact.query.filter(Contact.id.in_(contact_ids), Contact.user_id==uid).all():
                    emails.add(c.email)
            if group_ids:
                for g in ContactGroup.query.filter(ContactGroup.id.in_(group_ids), Contact.user_id==uid).all():
                    for c in g.contacts:
                        emails.add(c.email)
        
        if not emails:
            return False
        
        for addr in emails:
            ok, msg_id = send_email(addr, tpl.subject, tpl.body, mock=mock)
            log = EmailLog(
                user_id=uid,
                template_id=tpl.id,
                workflow_id=instance.workflow_id,
                instance_id=instance.id,
                node_id=node_id,
                recipient_email=addr,
                subject=tpl.subject,
                message_id=msg_id,
                status='sent' if ok else 'failed'
            )
            db.session.add(log)
            
            # 如果是首封邮件，记录 message_id 到实例
            if not instance.message_id:
                instance.message_id = msg_id
                db.session.commit()
        
        return True
    
    elif node_type == 'driver':
        # 处理 driver 节点 - 暂停等待事件
        steps = data.get('steps', [])
        step_order = data.get('stepOrder', ['event', 'condition', 'delay'])
        step_config = {s.get('id'): s for s in steps}
        enabled_steps = [s for s in step_order if step_config.get(s, {}).get('enabled', False)]
        
        # 提取等待的事件类型和条件
        waiting_event_type = None
        waiting_conditions = {}
        
        for step_id in enabled_steps:
            step = step_config.get(step_id, {})
            
            if step_id == 'event' and step.get('enabled'):
                waiting_event_type = step.get('event_type')
                if step.get('link_url'):
                    waiting_conditions['link_url'] = step.get('link_url')
            
            elif step_id == 'condition' and step.get('enabled'):
                waiting_conditions['field'] = step.get('field')
                waiting_conditions['operator'] = step.get('operator')
                waiting_conditions['value'] = step.get('value')
        
        # 更新实例为等待状态
        instance.status = 'waiting_event'
        instance.waiting_event_type = waiting_event_type
        instance.waiting_conditions = waiting_conditions if waiting_conditions else None
        instance.waiting_since = datetime.utcnow()
        db.session.commit()
        
        print(f"[Instance {instance.id}] Waiting for event: {waiting_event_type}")
        
        # Driver 节点暂停，不继续执行后续节点
        return False
    
    elif node_type == 'delay':
        # 处理延时节点
        delay_type = data.get('delayType', 'relative')
        recipient = instance.recipient_email
        
        next_ids = next_map.get(node_id, [])
        if not next_ids:
            return False
        
        if delay_type == 'relative':
            delay_value = data.get('delayValue', 1)
            delay_unit = data.get('delayUnit', 'hours')
            
            # 安排延时任务
            for next_id in next_ids:
                next_node = node_map.get(next_id)
                if next_node and next_node.get('data', {}).get('nodeType') == 'email':
                    job_id = schedule_relative_delay(
                        instance.workflow_id,
                        instance.id,
                        next_node.get('data'),
                        delay_value,
                        delay_unit,
                        recipient,
                        mock
                    )
                    if job_id:
                        instance.status = 'delayed'
                        instance.context = instance.context or {}
                        instance.context['scheduled_job_id'] = job_id
                        db.session.commit()
                        print(f"[Instance {instance.id}] Scheduled delay: {delay_value} {delay_unit}")
        else:
            delay_datetime = data.get('delayDateTime')
            
            for next_id in next_ids:
                next_node = node_map.get(next_id)
                if next_node and next_node.get('data', {}).get('nodeType') == 'email':
                    job_id = schedule_absolute_delay(
                        instance.workflow_id,
                        instance.id,
                        next_node.get('data'),
                        delay_datetime,
                        recipient,
                        mock
                    )
                    if job_id:
                        instance.status = 'delayed'
                        instance.context = instance.context or {}
                        instance.context['scheduled_job_id'] = job_id
                        db.session.commit()
                        print(f"[Instance {instance.id}] Scheduled absolute delay: {delay_datetime}")
        
        # 延时节点暂停，等待调度器恢复
        return False
    
    elif node_type == 'condition':
        # 条件判断节点
        field = data.get('field')
        operator = data.get('operator')
        value = data.get('value')
        
        # 手动执行时条件判断跳过
        print(f"[Instance {instance.id}] Condition: {field} {operator} {value}")
        return True
    
    elif node_type == 'event':
        # 事件触发节点
        event_type = data.get('event_type')
        print(f"[Instance {instance.id}] Event trigger: {event_type}")
        return True
    
    return True


def traverse_instance(instance, start_node, node_map, next_map, uid, mock=False):
    """遍历执行实例的工作流 - 支持并行路径"""
    visited = set()
    paused_branches = []  # 记录暂停的分支
    active_nodes = [start_node]  # 当前活跃节点队列

    while active_nodes:
        current = active_nodes.pop(0)
        node_id = current.get('id')

        if node_id in visited:
            continue
        visited.add(node_id)

        # 执行当前节点
        should_continue = execute_node_for_instance(instance, current, node_map, next_map, uid, mock)

        if not should_continue:
            # 节点暂停（driver/delay），记录暂停状态但不停止其他分支
            paused_branches.append({
                'node_id': node_id,
                'node': current,
                'status': instance.status
            })
            # 继续处理队列中的其他节点（并行路径）
            continue

        # 找到后续节点（可能有多个，表示并行分支）
        next_ids = next_map.get(node_id, [])
        for next_id in next_ids:
            next_node = node_map.get(next_id)
            if next_node and next_node.get('id') not in visited:
                active_nodes.append(next_node)

    # 检查最终状态
    if paused_branches:
        # 有分支暂停，保持当前状态
        print(f"[Instance {instance.id}] Paused {len(paused_branches)} branches")
    elif instance.status == 'running':
        # 所有分支完成
        instance.status = 'completed'
        instance.completed_at = datetime.utcnow()
        db.session.commit()
        print(f"[Instance {instance.id}] All branches completed")


@workflow_bp.route('/<int:wid>/execute', methods=['POST'])
@jwt_required()
def execute_workflow(wid):
    """执行工作流 - 为每个收件人创建独立实例"""
    uid = int(get_jwt_identity())
    w = Workflow.query.filter_by(id=wid, user_id=uid).first()
    if not w:
        return jsonify(msg='工作流不存在'), 404

    data = request.get_json() or {}
    mock = data.get('mock', False)

    # 解析工作流
    flow = json.loads(w.flow_data)
    nodes = flow.get('nodes', [])
    edges = flow.get('edges', [])
    
    if not nodes:
        return jsonify(msg='工作流为空'), 400

    # 构建节点和边映射
    node_map = {n['id']: n for n in nodes}
    next_map = {}
    for e in edges:
        source = e.get('source')
        target = e.get('target')
        if source and target:
            if source not in next_map:
                next_map[source] = []
            next_map[source].append(target)

    # 找到起始节点（没有入边的节点）
    target_ids = {e.get('target') for e in edges if e.get('target')}
    start_nodes = [n for n in nodes if n['id'] not in target_ids]
    start_nodes.sort(key=lambda n: (n.get('x', 0), n.get('y', 0)))
    
    if not start_nodes:
        return jsonify(msg='工作流没有起始节点'), 400

    # 找到第一个 email 节点来确定收件人列表
    first_email_node = None
    for node in start_nodes:
        if node.get('data', {}).get('nodeType') == 'email':
            first_email_node = node
            break
    
    if not first_email_node:
        return jsonify(msg='工作流起始节点必须是邮件节点'), 400

    # 获取收件人列表
    email_data = first_email_node.get('data', {})
    template_id = email_data.get('template_id')
    contact_ids = email_data.get('contact_ids', [])
    group_ids = email_data.get('group_ids', [])

    if not template_id:
        return jsonify(msg='邮件节点未配置模板'), 400

    tpl = EmailTemplate.query.filter_by(id=template_id, user_id=uid).first()
    if not tpl:
        return jsonify(msg='邮件模板不存在'), 404

    # 收集所有收件人
    recipient_emails = set()
    if contact_ids:
        for c in Contact.query.filter(Contact.id.in_(contact_ids), Contact.user_id==uid).all():
            recipient_emails.add(c.email)
    if group_ids:
        for g in ContactGroup.query.filter(ContactGroup.id.in_(group_ids), Contact.user_id==uid).all():
            for c in g.contacts:
                recipient_emails.add(c.email)

    if not recipient_emails:
        return jsonify(msg='没有收件人'), 400

    # 为每个收件人创建实例并开始执行
    created_instances = []
    
    for recipient_email in recipient_emails:
        # 创建工作流实例
        instance = WorkflowInstance(
            workflow_id=wid,
            user_id=uid,
            recipient_email=recipient_email,
            status='running',
            current_node_id=first_email_node.get('id'),
            context={
                'template_id': template_id,
                'contact_ids': contact_ids,
                'group_ids': group_ids,
                'mock': mock
            }
        )
        db.session.add(instance)
        db.session.commit()
        
        created_instances.append({
            'id': instance.id,
            'recipient_email': recipient_email,
            'status': 'running'
        })
        
        # 执行实例的工作流
        traverse_instance(instance, first_email_node, node_map, next_map, uid, mock)

    # 更新工作流最后执行时间
    w.last_executed_at = datetime.utcnow()
    db.session.commit()

    return jsonify({
        'msg': '工作流执行已启动',
        'instance_count': len(created_instances),
        'instances': created_instances,
        'mock': mock
    }), 200


@workflow_bp.route('/instance/<int:iid>/continue', methods=['POST'])
@jwt_required()
def continue_instance(iid):
    """从暂停状态恢复实例执行（内部 API，用于事件触发或延时恢复）"""
    uid = int(get_jwt_identity())
    
    instance = WorkflowInstance.query.filter_by(id=iid, user_id=uid).first()
    if not instance:
        return jsonify(msg='实例不存在'), 404
    
    if instance.status not in ['waiting_event', 'delayed']:
        return jsonify(msg=f'实例状态为 {instance.status}，无法恢复'), 400
    
    data = request.get_json() or {}
    event_data = data.get('event_data', {})
    mock = data.get('mock', False)
    
    # 解析工作流
    flow = json.loads(instance.workflow.flow_data)
    nodes = flow.get('nodes', [])
    edges = flow.get('edges', [])
    
    node_map = {n['id']: n for n in nodes}
    next_map = {}
    for e in edges:
        source = e.get('source')
        target = e.get('target')
        if source and target:
            if source not in next_map:
                next_map[source] = []
            next_map[source].append(target)
    
    # 找到当前节点
    current_node_id = instance.current_node_id
    if not current_node_id or current_node_id not in node_map:
        return jsonify(msg='无法找到当前节点'), 500
    
    current_node = node_map[current_node_id]
    node_data = current_node.get('data', {})
    node_type = node_data.get('nodeType', 'email')
    
    # 更新状态为 running
    instance.status = 'running'
    instance.waiting_event_type = None
    instance.waiting_conditions = None
    instance.waiting_since = None
    db.session.commit()
    
    # 处理 driver 节点的条件判断
    if node_type == 'driver':
        steps = node_data.get('steps', [])
        step_order = node_data.get('stepOrder', ['event', 'condition', 'delay'])
        step_config = {s.get('id'): s for s in steps}
        enabled_steps = [s for s in step_order if step_config.get(s, {}).get('enabled', False)]
        
        # 验证条件
        condition_passed = True
        for step_id in enabled_steps:
            step = step_config.get(step_id, {})
            
            if step_id == 'condition' and step.get('enabled'):
                field = step.get('field')
                operator = step.get('operator')
                value = step.get('value')
                
                if not evaluate_condition(field, operator, value, event_data):
                    condition_passed = False
                    print(f"[Instance {iid}] Condition not met: {field} {operator} {value}")
                    break
        
        if not condition_passed:
            instance.status = 'completed'
            instance.completed_at = datetime.utcnow()
            db.session.commit()
            return jsonify(msg='条件不满足，实例结束', instance_id=iid, status='completed'), 200
    
    # 找到后续节点并继续执行
    next_ids = next_map.get(current_node_id, [])
    if next_ids:
        for next_id in next_ids:
            next_node = node_map.get(next_id)
            if next_node:
                traverse_instance(instance, next_node, node_map, next_map, uid, mock)
    else:
        # 没有后续节点，标记完成
        instance.status = 'completed'
        instance.completed_at = datetime.utcnow()
        db.session.commit()
    
    return jsonify(
        msg='实例已恢复',
        instance_id=iid,
        status=instance.status
    ), 200
