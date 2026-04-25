import json
import uuid
import requests
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, EmailEvent, Workflow, WorkflowInstance, EmailLog, EmailTemplate, Contact, ContactGroup
from routes.email import send_email_with_binding
from services.scheduler import schedule_relative_delay, schedule_absolute_delay, get_scheduled_jobs, cancel_scheduled_job
from utils.sns_handler import handle_sns_message

webhooks_bp = Blueprint('webhooks', __name__)

# 创建模块级 logger，避免使用 current_app.logger
logger = logging.getLogger(__name__)


def evaluate_condition(field, operator, value, event_data):
    """评估条件是否满足"""
    field_value = None
    if field == 'event_type':
        field_value = event_data.get('event_type')
    elif field == 'link_url':
        field_value = event_data.get('link_url') or event_data.get('click', {}).get('link')
    elif field == 'recipient':
        field_value = event_data.get('recipient_email')

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


@webhooks_bp.route('/sns', methods=['POST'])
def handle_sns():
    """处理 AWS SNS 推送的邮件事件 - 新架构：通过 message_id 找到实例并触发恢复"""
    # SNS 发送的请求 Content-Type 是 text/plain，需要强制解析 JSON
    # 参考: https://docs.aws.amazon.com/sns/latest/dg/http-subscription-confirmation-json.html
    data = None

    # 记录请求信息
    logger.info("[SNS] Webhook received")
    logger.info(f"[SNS] Content-Type: {request.content_type}")

    # 首先尝试强制解析 JSON（忽略 Content-Type）
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        pass

    # 如果失败，尝试直接读取请求体并解析
    if not data:
        try:
            raw_data = request.get_data(as_text=True)
            logger.info(f"[SNS] Raw request body:\n{raw_data}")
            if raw_data:
                data = json.loads(raw_data)
        except Exception as e:
            logger.error(f"[SNS] Failed to parse request body: {e}")
    else:
        # 记录解析后的数据
        logger.info(f"[SNS] Parsed request data:\n{json.dumps(data, indent=2, ensure_ascii=False)}")

    if not data:
        logger.error(f"[SNS] No data received. Content-Type: {request.content_type}")
        return jsonify(msg='No data received'), 400

    # 处理 SNS 订阅确认
    if data.get('Type') == 'SubscriptionConfirmation':
        subscribe_url = data.get('SubscribeURL')
        topic_arn = data.get('TopicArn')
        token = data.get('Token')

        logger.info(f"[SNS] Subscription confirmation received")
        logger.info(f" Topic: {topic_arn}")
        logger.info(f" SubscribeURL: {subscribe_url}")

        # 必须访问 SubscribeURL 来确认订阅
        # 参考: https://docs.aws.amazon.com/sns/latest/dg/http-subscription-confirmation-json.html
        if subscribe_url:
            try:
                response = requests.get(subscribe_url, timeout=30)
                if response.status_code == 200:
                    logger.info(f"[SNS] Subscription confirmed successfully")
                    return jsonify(
                        msg='Subscription confirmed',
                        topic_arn=topic_arn,
                        status='confirmed'
                    ), 200
                else:
                    logger.error(f"[SNS] Failed to confirm subscription: {response.status_code}")
                    return jsonify(
                        msg='Failed to confirm subscription',
                        status_code=response.status_code
                    ), 500
            except Exception as e:
                logger.error(f"[SNS] Error confirming subscription: {str(e)}")
                return jsonify(
                    msg='Error confirming subscription',
                    error=str(e)
                ), 500
        else:
            logger.error("[SNS] SubscribeURL not found in confirmation message")
            return jsonify(msg='SubscribeURL not found'), 400

    # 解析 SNS 消息
    try:
        sns_message = json.loads(data.get('Message', '{}'))
    except:
        sns_message = data.get('Message', {})

    event_type = sns_message.get('eventType')
    mail_data = sns_message.get('mail', {})
    message_id = mail_data.get('messageId')

    # 提取收件人
    recipients = mail_data.get('commonHeaders', {}).get('to', [])
    recipient_email = recipients[0] if recipients else None

    if not event_type or not recipient_email:
        return jsonify(msg='Invalid event data'), 400

    # 查找等待该事件的实例
    instance = WorkflowInstance.query.filter_by(
        message_id=message_id,
        recipient_email=recipient_email,
        status='waiting_event'
    ).first()

    # 获取 SNS MessageId 用于去重
    sns_message_id = data.get('MessageId')

    if not instance:
        # 没有找到等待的实例，只记录事件（带去重和延迟监控）
        logger.info(f"[SNS] No waiting instance found for message_id: {message_id}")

        # 尝试从邮件日志获取 user_id
        email_log = EmailLog.query.filter_by(message_id=message_id).first()
        user_id = email_log.user_id if email_log else 1

        # 使用新的消息处理函数（带去重和延迟监控）
        event, is_duplicate, delay_seconds = handle_sns_message(
            sns_message_id=sns_message_id,
            message_id=message_id,
            event_type=event_type,
            recipient_email=recipient_email,
            sns_message_data=sns_message,
            user_id=user_id,
            instance_id=email_log.instance_id if email_log else None
        )

        if is_duplicate:
            return jsonify(
                msg='Duplicate event ignored',
                event_id=event.id if event else None,
                sns_message_id=sns_message_id
            ), 200

        return jsonify(
            msg='Event received but no waiting instance',
            event_id=event.id,
            delay_seconds=delay_seconds
        ), 200

    # 检查事件类型是否匹配（忽略大小写）
    waiting_event = instance.waiting_event_type.lower() if instance.waiting_event_type else None
    received_event = event_type.lower() if event_type else None
    if waiting_event and waiting_event != received_event:
        logger.info(f"[SNS] Event type mismatch: waiting {instance.waiting_event_type}, got {event_type}")
        return jsonify(msg=f'Event type mismatch, waiting for {instance.waiting_event_type}'), 200

    # 验证条件
    conditions_met = True
    if instance.waiting_conditions:
        field = instance.waiting_conditions.get('field')
        operator = instance.waiting_conditions.get('operator')
        value = instance.waiting_conditions.get('value')

        if field and operator:
            event_data = {
                'event_type': event_type,
                'recipient_email': recipient_email,
                **sns_message
            }
            conditions_met = evaluate_condition(field, operator, value, event_data)
            logger.info(f"[SNS] Condition check: {field} {operator} {value} = {conditions_met}")

    if not conditions_met:
        logger.info(f"[SNS] Conditions not met for instance {instance.id}")
        return jsonify(msg='Conditions not met'), 200

    # 使用新的消息处理函数（带去重和延迟监控）
    event, is_duplicate, delay_seconds = handle_sns_message(
        sns_message_id=sns_message_id,
        message_id=message_id,
        event_type=event_type,
        recipient_email=recipient_email,
        sns_message_data=sns_message,
        user_id=instance.user_id,
        instance_id=instance.id
    )

    if is_duplicate:
        return jsonify(
            msg='Duplicate event ignored',
            event_id=event.id if event else None,
            sns_message_id=sns_message_id
        ), 200

    logger.info(f"[SNS] Event matches instance {instance.id}, triggering continuation")

    # 触发实例继续执行
    mock_send = False
    result = continue_instance_execution(instance, sns_message, mock_send, source_event_id=event.id)

    return jsonify(
        msg='Event processed, instance triggered',
        event_id=event.id,
        instance_id=instance.id,
        result=result
    ), 200


def continue_instance_execution(instance, event_data, mock_send=False, source_event_id=None):
    """恢复实例执行 - 支持并行路径

    Args:
        instance: WorkflowInstance 对象
        event_data: 触发恢复的事件数据
        mock_send: 是否模拟发送
        source_event_id: 触发恢复的事件ID，用于记录到 EmailLog
    """
    from routes.workflow import execute_node_for_instance, evaluate_condition
    from models import NodeExecution
    import json

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

    current_node_id = instance.current_node_id
    if not current_node_id or current_node_id not in node_map:
        return {'error': 'Current node not found'}

    current_node = node_map[current_node_id]
    node_data = current_node.get('data', {})
    node_type = node_data.get('nodeType', 'email')

    # 从数据库加载已执行的节点（避免重复执行）
    executed_nodes = set()
    node_executions = NodeExecution.query.filter_by(instance_id=instance.id).all()
    for ne in node_executions:
        executed_nodes.add(ne.node_id)
    logger.info(f"[Instance {instance.id}] Already executed nodes: {executed_nodes}")

    # Driver 节点处理
    if node_type == 'driver':
        steps = node_data.get('steps', [])
        step_order = node_data.get('stepOrder', ['event', 'condition', 'delay'])
        step_config = {s.get('id'): s for s in steps}
        enabled_steps = [s for s in step_order if step_config.get(s, {}).get('enabled')]

        # 验证条件
        condition_passed = True
        has_delay_step = False
        delay_config = None

        for step_id in enabled_steps:
            step = step_config.get(step_id, {})

            if step_id == 'condition' and step.get('enabled'):
                field = step.get('field')
                operator = step.get('operator')
                value = step.get('value')

                if not evaluate_condition(field, operator, value, event_data):
                    condition_passed = False
                    break

            elif step_id == 'delay' and step.get('enabled'):
                has_delay_step = True
                delay_config = step

        if not condition_passed:
            instance.status = 'completed'
            instance.completed_at = datetime.utcnow()
            db.session.commit()
            return {'status': 'completed', 'reason': 'conditions_not_met'}

        # 找到后续节点
        next_ids = next_map.get(current_node_id, [])
        if not next_ids:
            instance.status = 'completed'
            instance.completed_at = datetime.utcnow()
            db.session.commit()
            return {'status': 'completed', 'reason': 'no_more_nodes'}

        # 如果有延时步骤，调度延时任务而不是立即执行
        if has_delay_step and delay_config:
            logger.info(f"[Instance {instance.id}] Delay step enabled, scheduling delay task")
            delay_type = delay_config.get('delayType', 'relative')
            recipient = instance.recipient_email

            for next_id in next_ids:
                next_node = node_map.get(next_id)
                if next_node and next_node.get('data', {}).get('nodeType') == 'email':
                    # 检查该节点是否已经被执行过（避免重复调度）
                    if next_id in executed_nodes:
                        logger.info(f"[Instance {instance.id}] Node {next_id} already executed, skipping delay schedule")
                        continue

                    # 构建包含id的node_data
                    node_data_with_id = next_node.get('data', {}).copy()
                    node_data_with_id['id'] = next_id

                    # 保存 source_event_id 和 event_data 到实例上下文
                    if source_event_id:
                        from sqlalchemy.orm.attributes import flag_modified
                        instance.context = instance.context or {}
                        instance.context['delayed_source_event_id'] = source_event_id
                        instance.context['delayed_event_data'] = event_data
                        flag_modified(instance, 'context')
                        db.session.commit()
                        logger.info(f"[Instance {instance.id}] Saved event context: source_event_id={source_event_id}")

                    if delay_type == 'relative':
                        delay_value = delay_config.get('delayValue', 1)
                        delay_unit = delay_config.get('delayUnit', 'hours')
                        job_id = schedule_relative_delay(
                            instance.workflow_id,
                            instance.id,
                            node_data_with_id,
                            delay_value,
                            delay_unit,
                            recipient,
                            mock_send
                        )
                        if job_id:
                            from sqlalchemy.orm.attributes import flag_modified
                            instance.status = 'delayed'
                            instance.context = instance.context or {}
                            instance.context['scheduled_job_id'] = job_id
                            flag_modified(instance, 'context')
                            db.session.commit()
                            logger.info(f"[Instance {instance.id}] Scheduled relative delay: {delay_value} {delay_unit}")
                    else:
                        delay_datetime = delay_config.get('delayDateTime')
                        job_id = schedule_absolute_delay(
                            instance.workflow_id,
                            instance.id,
                            node_data_with_id,
                            delay_datetime,
                            recipient,
                            mock_send
                        )
                        if job_id:
                            from sqlalchemy.orm.attributes import flag_modified
                            instance.status = 'delayed'
                            instance.context = instance.context or {}
                            instance.context['scheduled_job_id'] = job_id
                            flag_modified(instance, 'context')
                            db.session.commit()
                            logger.info(f"[Instance {instance.id}] Scheduled absolute delay: {delay_datetime}")

            # 延时任务已调度，不立即执行后续节点
            return {'status': 'delayed', 'reason': 'delay_scheduled'}

        # 没有延时步骤，继续执行后续节点
        # 更新状态为运行中（在确认没有延时步骤后）
        instance.status = 'running'
        instance.waiting_event_type = None
        instance.waiting_conditions = None
        instance.waiting_since = None
        db.session.commit()

        active_nodes = []
        for next_id in next_ids:
            next_node = node_map.get(next_id)
            if next_node and next_node.get('id') not in executed_nodes:
                active_nodes.append(next_node)

        # 遍历所有活跃节点（支持并行分支）
        visited = executed_nodes.copy()
        visited.add(current_node_id)
        paused_branches = []

        while active_nodes:
            node = active_nodes.pop(0)
            node_id = node.get('id')

            if node_id in visited:
                logger.info(f"[Instance {instance.id}] Skipping already executed node: {node_id}")
                continue
            visited.add(node_id)

            # 执行节点，传递 source_event_id 和 event_data
            should_continue = execute_node_for_instance(
                instance, node, node_map, next_map,
                instance.user_id, mock_send,
                resumed_event_data=event_data,
                source_event_id=source_event_id
            )

            if not should_continue:
                paused_branches.append({
                    'node_id': node_id,
                    'status': instance.status
                })
                continue

            # 找到后续节点
            subsequent_ids = next_map.get(node_id, [])
            for sid in subsequent_ids:
                snode = node_map.get(sid)
                if snode and sid not in visited:
                    active_nodes.append(snode)

        # 检查最终状态
        if paused_branches:
            logger.info(f"[Instance {instance.id}] Event recovery paused {len(paused_branches)} branches")
        elif instance.status == 'running':
            instance.status = 'completed'
            instance.completed_at = datetime.utcnow()
            db.session.commit()

        return {
            'status': instance.status,
            'current_node': instance.current_node_id,
            'branches_paused': len(paused_branches) if paused_branches else 0
        }

    # 如果不是 driver 节点，继续正常执行
    instance.status = 'running'
    instance.waiting_event_type = None
    instance.waiting_conditions = None
    instance.waiting_since = None
    db.session.commit()

    return {'status': instance.status, 'reason': 'not_driver_node'}


@webhooks_bp.route('/simulate/event', methods=['POST'])
@jwt_required()
def simulate_event():
    """模拟 SES 事件（用于测试驱动节点）"""
    from flask import request
    uid = int(get_jwt_identity())
    data = request.get_json()

    event_type = data.get('event_type', 'open')
    message_id = data.get('message_id')
    recipient_email = data.get('recipient_email')
    event_data = data.get('event_data', {})
    mock_send = data.get('mock_send', False)

    if not message_id or not recipient_email:
        return jsonify(msg='message_id and recipient_email are required'), 400

    # 查找匹配的实例（添加调试日志）
    logger.info(f"[Simulate] Looking for instance: message_id={message_id}, recipient={recipient_email}, status=waiting_event")
    
    # 先检查所有该message_id的实例
    all_instances = WorkflowInstance.query.filter_by(message_id=message_id).all()
    logger.info(f"[Simulate] Found {len(all_instances)} instances with message_id={message_id}")
    for inst in all_instances:
        logger.info(f"[Simulate]   Instance {inst.id}: status={inst.status}, recipient={inst.recipient_email}, waiting_type={inst.waiting_event_type}")
    
    instance = WorkflowInstance.query.filter_by(
        message_id=message_id,
        recipient_email=recipient_email,
        status='waiting_event'
    ).first()

    if not instance:
        # 尝试模糊匹配（忽略大小写）
        from sqlalchemy import func
        instance = WorkflowInstance.query.filter(
            WorkflowInstance.message_id == message_id,
            func.lower(WorkflowInstance.recipient_email) == recipient_email.lower(),
            WorkflowInstance.status == 'waiting_event'
        ).first()
        
        if not instance:
            return jsonify(
                msg='No waiting instance found for this message_id',
                debug={
                    'searched_message_id': message_id,
                    'searched_recipient': recipient_email,
                    'required_status': 'waiting_event',
                    'found_instances_count': len(all_instances),
                    'found_instances': [
                        {
                            'id': inst.id,
                            'status': inst.status,
                            'recipient': inst.recipient_email,
                            'waiting_event_type': inst.waiting_event_type
                        } for inst in all_instances
                    ]
                }
            ), 404

    # 检查事件类型是否匹配（忽略大小写）
    if instance.waiting_event_type and instance.waiting_event_type != event_type.lower():
        logger.info(f"[Simulate] Event type mismatch: waiting {instance.waiting_event_type}, got {event_type}")
        return jsonify(msg=f'Event type mismatch, waiting for {instance.waiting_event_type}'), 200

    logger.info(f"[Simulate] Event matches instance {instance.id}, triggering continuation")

    # 创建 EmailEvent（与 SNS 处理一致）
    from models import EmailEvent
    from datetime import datetime
    event = EmailEvent(
        user_id=instance.user_id,
        instance_id=instance.id,
        message_id=message_id,
        event_type=event_type.lower(),
        recipient_email=recipient_email,
        event_data=event_data,
        occurred_at=datetime.utcnow().isoformat(),
        sns_message_id=f"simulate-{int(datetime.utcnow().timestamp())}",
        sns_received_at=datetime.utcnow(),
        sns_delay_seconds=0.0
    )
    
    # 查找对应的 EmailLog 并关联
    email_log = EmailLog.query.filter_by(message_id=message_id).first()
    if email_log:
        event.source_email_log_id = email_log.id
        
    db.session.add(event)
    db.session.commit()
    logger.info(f"[Simulate] Created EmailEvent: id={event.id}")

    # 触发实例继续执行，传递 event.id 作为 source_event_id
    result = continue_instance_execution(instance, event_data, mock_send, source_event_id=event.id)

    return jsonify({
        'msg': 'Event processed, instance triggered',
        'event_id': event.id,
        'instance_id': instance.id,
        'result': result
    }), 200


@webhooks_bp.route('/events', methods=['GET'])
@jwt_required()
def list_events():
    """获取邮件事件列表"""
    from flask import request
    uid = int(get_jwt_identity())

    # 分页参数
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    # 限制每页数量
    if per_page > 100:
        per_page = 100

    # 可选筛选参数
    event_type = request.args.get('event_type')
    message_id = request.args.get('message_id')

    # 构建查询
    query = EmailEvent.query.filter_by(user_id=uid)

    if event_type:
        query = query.filter_by(event_type=event_type)
    if message_id:
        query = query.filter_by(message_id=message_id)

    # 按时间倒序排序
    query = query.order_by(EmailEvent.created_at.desc())

    # 分页
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'events': [{
            'id': e.id,
            'event_type': e.event_type,
            'recipient_email': e.recipient_email,
            'message_id': e.message_id,
            'instance_id': e.instance_id,
            'event_data': e.event_data,
            'occurred_at': e.occurred_at.isoformat() if e.occurred_at else None,
            'created_at': e.created_at.isoformat() if e.created_at else None,
            'sns_message_id': e.sns_message_id,
            'sns_delay_seconds': e.sns_delay_seconds
        } for e in pagination.items],
        'pagination': {
            'page': pagination.page,
            'per_page': pagination.per_page,
            'total': pagination.total,
            'pages': pagination.pages,
            'has_next': pagination.has_next,
            'has_prev': pagination.has_prev
        }
    }), 200


@webhooks_bp.route('/scheduled', methods=['GET'])
@jwt_required()
def list_scheduled_jobs():
    """获取预定的延时任务列表"""
    jobs = get_scheduled_jobs()
    return jsonify(jobs=jobs), 200


@webhooks_bp.route('/scheduled/<job_id>', methods=['DELETE'])
@jwt_required()
def cancel_scheduled(job_id):
    """取消预定的延时任务"""
    success = cancel_scheduled_job(job_id)
    if success:
        return jsonify(msg='Job cancelled'), 200
    return jsonify(msg='Job not found'), 404
