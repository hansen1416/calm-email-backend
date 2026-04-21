import json
import uuid
import requests
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, EmailEvent, Workflow, WorkflowInstance, EmailLog, EmailTemplate, Contact, ContactGroup
from routes.email import send_email
from services.scheduler import schedule_relative_delay, schedule_absolute_delay, get_scheduled_jobs, cancel_scheduled_job
from utils.sns_handler import handle_sns_message

webhooks_bp = Blueprint('webhooks', __name__)


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
    current_app.logger.info("=" * 60)
    current_app.logger.info("[SNS] Webhook received")
    current_app.logger.info(f"[SNS] Content-Type: {request.content_type}")
    current_app.logger.info(f"[SNS] Headers: {dict(request.headers)}")

    # 首先尝试强制解析 JSON（忽略 Content-Type）
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        pass

    # 如果失败，尝试直接读取请求体并解析
    if not data:
        try:
            raw_data = request.get_data(as_text=True)
            current_app.logger.info(f"[SNS] Raw request body:\n{raw_data}")
            if raw_data:
                data = json.loads(raw_data)
        except Exception as e:
            current_app.logger.error(f"[SNS] Failed to parse request body: {e}")
    else:
        # 记录解析后的数据
        current_app.logger.info(f"[SNS] Parsed request data:\n{json.dumps(data, indent=2, ensure_ascii=False)}")

    if not data:
        current_app.logger.error(f"[SNS] No data received. Content-Type: {request.content_type}")
        return jsonify(msg='No data received'), 400

    # 处理 SNS 订阅确认
    if data.get('Type') == 'SubscriptionConfirmation':
        subscribe_url = data.get('SubscribeURL')
        topic_arn = data.get('TopicArn')
        token = data.get('Token')
        
        current_app.logger.info(f"[SNS] Subscription confirmation received")
        current_app.logger.info(f"  Topic: {topic_arn}")
        current_app.logger.info(f"  SubscribeURL: {subscribe_url}")
        
        # 必须访问 SubscribeURL 来确认订阅
        # 参考: https://docs.aws.amazon.com/sns/latest/dg/http-subscription-confirmation-json.html
        if subscribe_url:
            try:
                response = requests.get(subscribe_url, timeout=30)
                if response.status_code == 200:
                    current_app.logger.info(f"[SNS] Subscription confirmed successfully")
                    return jsonify(
                        msg='Subscription confirmed',
                        topic_arn=topic_arn,
                        status='confirmed'
                    ), 200
                else:
                    current_app.logger.error(f"[SNS] Failed to confirm subscription: {response.status_code}")
                    return jsonify(
                        msg='Failed to confirm subscription',
                        status_code=response.status_code
                    ), 500
            except Exception as e:
                current_app.logger.error(f"[SNS] Error confirming subscription: {str(e)}")
                return jsonify(
                    msg='Error confirming subscription',
                    error=str(e)
                ), 500
        else:
            current_app.logger.error("[SNS] SubscribeURL not found in confirmation message")
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
        print(f"[SNS] No waiting instance found for message_id: {message_id}")

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
        print(f"[SNS] Event type mismatch: waiting {instance.waiting_event_type}, got {event_type}")
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
            print(f"[SNS] Condition check: {field} {operator} {value} = {conditions_met}")

    if not conditions_met:
        print(f"[SNS] Conditions not met for instance {instance.id}")
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

    print(f"[SNS] Event matches instance {instance.id}, triggering continuation")

    # 触发实例继续执行
    mock_send = current_app.config.get('MOCK_EMAIL_SEND', False)
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
    print(f"[Instance {instance.id}] Already executed nodes: {executed_nodes}")

    # Driver 节点处理
    if node_type == 'driver':
        steps = node_data.get('steps', [])
        step_order = node_data.get('stepOrder', ['event', 'condition', 'delay'])
        step_config = {s.get('id'): s for s in steps}
        enabled_steps = [s for s in step_order if step_config.get(s, {}).get('enabled', False)]

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
            print(f"[Instance {instance.id}] Delay step enabled, scheduling delay task")
            delay_type = delay_config.get('delayType', 'relative')
            recipient = instance.recipient_email

            for next_id in next_ids:
                next_node = node_map.get(next_id)
                if next_node and next_node.get('data', {}).get('nodeType') == 'email':
                    # 检查该节点是否已经被执行过（避免重复调度）
                    if next_id in executed_nodes:
                        print(f"[Instance {instance.id}] Node {next_id} already executed, skipping delay schedule")
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
                        print(f"[Instance {instance.id}] Saved event context: source_event_id={source_event_id}")

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
                            print(f"[Instance {instance.id}] Scheduled relative delay: {delay_value} {delay_unit}")
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
                            print(f"[Instance {instance.id}] Scheduled absolute delay: {delay_datetime}")

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
                print(f"[Instance {instance.id}] Skipping already executed node: {node_id}")
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
            print(f"[Instance {instance.id}] Event recovery paused {len(paused_branches)} branches")
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
    """模拟邮件事件（用于测试和调试）- 现在与SNS处理逻辑一致"""
    uid = int(get_jwt_identity())
    data = request.get_json()

    event_type = data.get('event_type')
    message_id = data.get('message_id')
    recipient_email = data.get('recipient_email')
    event_data = data.get('event_data', {})
    occurred_at = data.get('occurred_at')
    mock_send = data.get('mock_send', False)

    if not event_type or not message_id or not recipient_email:
        return jsonify(msg='Missing required fields'), 400

    valid_events = ['send', 'delivery', 'open', 'click', 'bounce', 'complaint', 'deliveryDelay', 'reject', 'renderingFailure']
    if event_type.lower() not in valid_events:
        return jsonify(msg=f'Invalid event_type. Must be one of: {valid_events}'), 400

    # 解析时间
    occurred_time = None
    if occurred_at:
        try:
            occurred_time = datetime.fromisoformat(occurred_at.replace('Z', '+00:00'))
        except:
            occurred_time = datetime.utcnow()
    else:
        occurred_time = datetime.utcnow()

    # 查找等待该事件的实例（与SNS处理逻辑一致）
    instance = WorkflowInstance.query.filter_by(
        message_id=message_id,
        recipient_email=recipient_email,
        status='waiting_event'
    ).first()

    # 查找邮件日志获取 user_id
    email_log = EmailLog.query.filter_by(message_id=message_id).first()
    actual_uid = email_log.user_id if email_log else uid

    # 存储事件
    event = EmailEvent(
        user_id=actual_uid,
        instance_id=instance.id if instance else None,
        message_id=message_id,
        event_type=event_type.lower(),
        recipient_email=recipient_email,
        event_data=event_data,
        occurred_at=occurred_time
    )
    if email_log:
        event.source_email_log_id = email_log.id
    db.session.add(event)
    db.session.commit()

    # 如果没有等待的实例，只记录事件
    if not instance:
        print(f"[Simulate] No waiting instance found for message_id: {message_id}")
        return jsonify(msg='Event simulated but no waiting instance', event_id=event.id), 200

    # 检查事件类型是否匹配
    if instance.waiting_event_type and instance.waiting_event_type != event_type.lower():
        print(f"[Simulate] Event type mismatch: waiting {instance.waiting_event_type}, got {event_type}")
        return jsonify(msg=f'Event type mismatch, waiting for {instance.waiting_event_type}'), 200

    print(f"[Simulate] Event matches instance {instance.id}, triggering continuation")

    # 触发实例继续执行（与SNS处理逻辑完全一致）
    result = continue_instance_execution(instance, event_data, mock_send, source_event_id=event.id)

    return jsonify(
        msg='Event processed, instance triggered',
        event_id=event.id,
        instance_id=instance.id,
        result=result
    ), 200


def trigger_workflows(event_type, message_id, recipient_email, event_data, mock_send=False, workflow_id=None, node_id=None):
    """触发相关的工作流"""
    triggered = []

    if workflow_id:
        workflow = Workflow.query.get(workflow_id)
        if workflow and workflow.status == 'active':
            print(f"[Trigger] Continuing from workflow {workflow.id}:{workflow.name}")
            result = execute_workflow_from_trigger(workflow, node_id, event_data, mock_send, message_id, recipient_email)
            triggered.append({
                'workflow_id': workflow.id,
                'workflow_name': workflow.name,
                'result': result,
                'continue_from_node': node_id
            })

    return triggered


def execute_workflow_from_trigger(workflow, source_node_id, event_data, mock_send=False, message_id=None, recipient_email=None):
    """从触发节点开始执行工作流

    Args:
        workflow: 工作流对象
        source_node_id: 起始节点ID（从该节点继续执行，而非从头开始）
        event_data: 事件数据
        mock_send: 是否模拟发送
        message_id: 消息ID（用于查找关联的邮件）
        recipient_email: 收件人邮箱
    """
    flow = json.loads(workflow.flow_data)
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

    results = []
    visited = set()

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

    def process_driver_node(node_data, event_data):
        """处理事件驱动节点（driver类型）"""
        steps = node_data.get('steps', [])
        step_order = node_data.get('stepOrder', ['event', 'condition', 'delay'])

        step_config = {s.get('id'): s for s in steps}
        enabled_steps = [s for s in step_order if step_config.get(s, {}).get('enabled', False)]

        label = node_data.get('label', '事件驱动节点')
        print(f"[Workflow] Driver node: {label}")
        print(f"  Enabled steps: {enabled_steps}")

        if not enabled_steps:
            print(f"  [PASS] No enabled steps, pass through")
            return [{'step': 'none', 'status': 'passed'}]

        step_results = []

        for step_id in enabled_steps:
            step = step_config.get(step_id, {})
            step_name = step.get('name', step_id)
            print(f"  Processing step: {step_id} - {step_name}")

            if step_id == 'event':
                event_type = step.get('event_type')
                link_url = step.get('link_url', '')

                print(f"    Configured event type: {event_type or 'any'}")
                print(f"    Link URL: {link_url or 'N/A'}")

                current_event_type = event_data.get('event_type', '')

                if event_type and current_event_type != event_type:
                    print(f"    [SKIP] Event type mismatch: expected {event_type}, got {current_event_type}")
                    return []

                if event_type == 'click' or current_event_type == 'click':
                    if link_url:
                        actual_link = event_data.get('click', {}).get('link') or event_data.get('link_url', '') or event_data.get('link', '')
                        if link_url and link_url not in actual_link:
                            print(f"    [SKIP] Link URL mismatch: expected '{link_url}', got '{actual_link}'")
                            return []

                print(f"    [PASS] Event check passed")
                step_results.append({'step': 'event', 'status': 'passed'})

            elif step_id == 'condition':
                field = step.get('field')
                operator = step.get('operator')
                value = step.get('value')

                print(f"    Field: {field}, Operator: {operator}, Value: {value}")

                condition_met = evaluate_condition(field, operator, value, event_data)
                print(f"    Condition result: {condition_met}")

                if not condition_met:
                    print(f"    [SKIP] Condition not met, skip this branch")
                    return []

                print(f"    [PASS] Condition passed")
                step_results.append({'step': 'condition', 'status': 'passed'})

            elif step_id == 'delay':
                delay_type = step.get('delayType', 'relative')

                if delay_type == 'relative':
                    delay_value = step.get('delayValue', 1)
                    delay_unit = step.get('delayUnit', 'hours')
                    print(f"    Relative delay: {delay_value} {delay_unit}")
                    print(f"    [INFO] Delay would be executed at runtime")
                else:
                    delay_datetime = step.get('delayDateTime')
                    print(f"    Absolute delay: {delay_datetime}")
                    print(f"    [INFO] Scheduled execution at: {delay_datetime}")

                step_results.append({'step': 'delay', 'status': 'processed'})

        return step_results

    def execute_node(node_id):
        if node_id in visited:
            return
        visited.add(node_id)

        node = node_map.get(node_id)
        if not node:
            return

        data = node.get('data', {})
        node_type = data.get('nodeType', 'email')

        if node_type == 'driver':
            step_results = process_driver_node(data, event_data)
            if not step_results:
                print(f"  [SKIP] Driver node conditions not met, skip execution")
                return

            print(f"  [CONTINUE] Driver node passed, continue to next nodes")

        elif node_type == 'email':
            template_id = data.get('template_id')
            contact_ids = data.get('contact_ids', [])
            group_ids = data.get('group_ids', [])
            label = data.get('label', '未命名节点')

            if not template_id:
                return

            tpl = EmailTemplate.query.filter_by(id=template_id, user_id=workflow.user_id).first()
            if not tpl:
                return

            emails = set()
            if contact_ids:
                for c in Contact.query.filter(Contact.id.in_(contact_ids), Contact.user_id==workflow.user_id).all():
                    emails.add(c.email)
            if group_ids:
                for g in ContactGroup.query.filter(ContactGroup.id.in_(group_ids), Contact.user_id==workflow.user_id).all():
                    for c in g.contacts:
                        emails.add(c.email)

            recipient = event_data.get('recipient_email') or event_data.get('mail', {}).get('commonHeaders', {}).get('to', [None])[0]
            if recipient:
                emails.add(recipient)

            for addr in emails:
                ok, msg_id = send_email(addr, tpl.subject, tpl.body, mock=mock_send)
                log = EmailLog(
                    user_id=workflow.user_id,
                    template_id=tpl.id,
                    workflow_id=workflow.id,
                    node_id=node_id,
                    recipient_email=addr,
                    subject=tpl.subject,
                    message_id=msg_id,
                    status='sent' if ok else 'failed'
                )
                db.session.add(log)
                results.append(dict(node=label, template=tpl.name, email=addr, status='sent' if ok else 'failed', message_id=msg_id))

        elif node_type == 'delay':
            delay_type = data.get('delayType', 'relative')
            node_id = data.get('id', 'unknown')

            recipient = event_data.get('recipient_email') or event_data.get('mail', {}).get('commonHeaders', {}).get('to', [None])[0]

            if delay_type == 'relative':
                delay_value = data.get('delayValue', 1)
                delay_unit = data.get('delayUnit', 'hours')
                print(f"[Workflow] Delay node: {delay_value} {delay_unit}")

                next_ids = next_map.get(node_id, [])
                for next_id in next_ids:
                    next_node = node_map.get(next_id)
                    if next_node and next_node.get('data', {}).get('nodeType') == 'email':
                        job_id = schedule_relative_delay(
                            workflow.id,
                            next_id,
                            next_node.get('data'),
                            delay_value,
                            delay_unit,
                            recipient,
                            mock_send
                        )
                        print(f"  [SCHEDULED] Job ID: {job_id}")
                        results.append({
                            'node': 'delay',
                            'status': 'scheduled',
                            'job_id': job_id,
                            'delay': f'{delay_value} {delay_unit}'
                        })
            else:
                delay_datetime = data.get('delayDateTime')
                print(f"[Workflow] Delay node (absolute): {delay_datetime}")

                next_ids = next_map.get(node_id, [])
                for next_id in next_ids:
                    next_node = node_map.get(next_id)
                    if next_node and next_node.get('data', {}).get('nodeType') == 'email':
                        job_id = schedule_absolute_delay(
                            workflow.id,
                            next_id,
                            next_node.get('data'),
                            delay_datetime,
                            recipient,
                            mock_send
                        )
                        print(f"  [SCHEDULED] Job ID: {job_id}")
                        results.append({
                            'node': 'delay',
                            'status': 'scheduled',
                            'job_id': job_id,
                            'scheduled_at': delay_datetime
                        })

        elif node_type == 'condition':
            field = data.get('field')
            operator = data.get('operator')
            value = data.get('value')
            condition_met = evaluate_condition(field, operator, value, event_data)
            print(f"[Workflow] Condition node: {field} {operator} {value} = {condition_met}")
            if not condition_met:
                return

        for next_id in next_map.get(node_id, []):
            execute_node(next_id)

    if source_node_id:
        execute_node(source_node_id)
    else:
        target_ids = {e.get('target') for e in edges if e.get('target')}
        start_nodes = [n for n in nodes if n['id'] not in target_ids]
        for start_node in start_nodes:
            execute_node(start_node['id'])

    db.session.commit()
    return results


@webhooks_bp.route('/events', methods=['GET'])
@jwt_required()
def list_events():
    """获取邮件事件列表"""
    uid = int(get_jwt_identity())

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    event_type = request.args.get('event_type')
    recipient = request.args.get('recipient')

    query = EmailEvent.query.filter_by(user_id=uid)

    if event_type:
        query = query.filter(EmailEvent.event_type == event_type)
    if recipient:
        query = query.filter(EmailEvent.recipient_email.like(f'%{recipient}%'))

    pagination = query.order_by(EmailEvent.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    result = []
    for e in pagination.items:
        result.append({
            'id': e.id,
            'message_id': e.message_id,
            'event_type': e.event_type,
            'recipient_email': e.recipient_email,
            'event_data': e.event_data,
            'occurred_at': e.occurred_at.strftime('%Y-%m-%d %H:%M:%S') if e.occurred_at else None,
            'created_at': e.created_at.strftime('%Y-%m-%d %H:%M:%S') if e.created_at else None
        })

    return jsonify({
        'events': result,
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page
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