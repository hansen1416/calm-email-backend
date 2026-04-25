import json
import logging
from datetime import datetime, timedelta
from apscheduler.triggers.date import DateTrigger
from flask_apscheduler import APScheduler

scheduler = APScheduler()
logger = logging.getLogger(__name__)


def init_scheduler(app):
    """初始化调度器，配置数据库存储"""
    # 先配置调度器参数
    app.config['SCHEDULER_API_ENABLED'] = True
    # 使用本地时区避免 UTC 转换问题
    app.config['SCHEDULER_TIMEZONE'] = 'Asia/Shanghai'

    try:
        # 延迟导入 SQLAlchemyJobStore 避免循环导入
        from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
        from models import db

        # 配置使用数据库存储 - 使用已经存在的 engine
        jobstores = {
            'default': SQLAlchemyJobStore(engine=db.engine, tablename='apscheduler_jobs')
        }
        app.config['SCHEDULER_JOBSTORES'] = jobstores

        # 配置任务执行器
        app.config['SCHEDULER_EXECUTORS'] = {
            'default': {'type': 'threadpool', 'max_workers': 10}
        }

        # 配置任务默认参数
        app.config['SCHEDULER_JOB_DEFAULTS'] = {
            'coalesce': True, # 合并错过的任务
            'max_instances': 1, # 每个任务只允许一个实例运行
            'misfire_grace_time': 3600 # 允许1小时的容错时间
        }

        logger.info("[Scheduler] Using SQLAlchemyJobStore for persistence")
    except Exception as e:
        logger.error(f"[Scheduler] Failed to use SQLAlchemyJobStore: {e}")

    scheduler.init_app(app)
    scheduler._app = app # 存储 app 实例供任务使用
    scheduler.start()
    logger.info("[Scheduler] Scheduler started successfully")


def shutdown_scheduler():
    """优雅关闭调度器"""
    if scheduler.running:
        scheduler.shutdown(wait=True)
        logger.info("[Scheduler] Scheduler shutdown")


def _create_app_context():
    """创建 Flask 应用上下文（用于 gunicorn 多 worker 环境）"""
    from flask import Flask
    from config import Config

    logger.info("[Scheduler] Creating new Flask app context for delayed task")

    app = Flask(__name__)
    app.config.from_object(Config)

    # 重新初始化 db
    from models import db
    db.init_app(app)

    # 测试数据库连接
    with app.app_context():
        try:
            db.session.execute('SELECT 1')
            logger.info("[Scheduler] Database connection test passed")
        except Exception as e:
            logger.error(f"[Scheduler] Database connection test failed: {e}")

    return app


def get_scheduled_jobs():
    """获取所有预定的延时任务列表"""
    jobs = scheduler.get_jobs()
    return [{
        'id': job.id,
        'name': job.name,
        'trigger': str(job.trigger),
        'next_run_time': job.next_run_time.isoformat() if job.next_run_time else None
    } for job in jobs]


def cancel_scheduled_job(job_id):
    """取消指定的延时任务

    Args:
        job_id: 任务ID

    Returns:
        bool: 是否成功取消
    """
    try:
        scheduler.remove_job(job_id)
        logger.info(f"[Scheduler] Cancelled job: {job_id}")
        return True
    except Exception as e:
        logger.error(f"[Scheduler] Failed to cancel job {job_id}: {e}")
        return False


def execute_delayed_node(workflow_id, instance_id, node_data, recipient_email, mock_send=False):
    """执行延时节点后的邮件发送

    恢复实例执行，继续后续节点
    """
    logger.info(f"[Scheduler] Starting delayed node execution: workflow={workflow_id}, instance={instance_id}")

    # 在 gunicorn 多 worker 环境下，必须重新创建 app 上下文
    try:
        app = _create_app_context()
    except Exception as e:
        logger.error(f"[Scheduler] Failed to create app context: {e}")
        return

    if not app:
        logger.error("[Scheduler] Failed to create Flask app context")
        return

    with app.app_context():
        try:
            # 延迟导入避免循环导入
            from models import db, NodeExecution, WorkflowInstance, Workflow
            from routes.workflow import execute_node_for_instance

            # 获取实例
            instance = WorkflowInstance.query.get(instance_id)
            if not instance:
                logger.error(f"[Scheduler] Instance {instance_id} not found")
                return

            if instance.status != 'delayed':
                logger.warning(f"[Scheduler] Instance {instance_id} status is {instance.status}, expected 'delayed'")
                return

            # 检查传入的 node_data 对应的节点是否已执行过（防止重复执行）
            node_id = node_data.get('id') if node_data else None
            if node_id:
                existing_execution = NodeExecution.query.filter_by(
                    instance_id=instance_id,
                    node_id=node_id
                ).first()
                if existing_execution:
                    logger.info(f"[Scheduler] Node {node_id} already executed for instance {instance_id}, skipping")
                    return

            logger.info(f"[Scheduler] Resuming delayed instance {instance_id}")

            # 获取保存的 event 上下文（必须在 commit 之前读取）
            source_event_id = instance.context.get('delayed_source_event_id') if instance.context else None
            resumed_event_data = instance.context.get('delayed_event_data') if instance.context else None

            if source_event_id:
                logger.info(f"[Scheduler] Restored source_event_id: {source_event_id}")

            # 更新状态为 running
            instance.status = 'running'
            db.session.commit()

            # 获取工作流
            workflow = Workflow.query.get(workflow_id)
            if not workflow:
                logger.error(f"[Scheduler] Workflow {workflow_id} not found")
                return

            # 解析工作流
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

            # 直接使用传入的 node_data 作为要执行的节点
            if not node_data:
                logger.error(f"[Scheduler] No node_data provided for instance {instance_id}")
                return

            target_node_id = node_data.get('id')
            if not target_node_id:
                logger.error(f"[Scheduler] No node_id in node_data for instance {instance_id}")
                return

            if target_node_id not in node_map:
                logger.error(f"[Scheduler] Node {target_node_id} not found in workflow {workflow_id}")
                return

            target_node = node_map[target_node_id]
            logger.info(f"[Scheduler] Executing node: {target_node_id}")

            active_nodes = [target_node]
            visited = set([instance.current_node_id])
            paused_branches = []

            while active_nodes:
                node = active_nodes.pop(0)
                node_id = node.get('id')

                if node_id in visited:
                    continue
                visited.add(node_id)

                should_continue = execute_node_for_instance(
                    instance, node, node_map, next_map,
                    workflow.user_id, mock_send,
                    resumed_event_data=resumed_event_data,
                    source_event_id=source_event_id
                )

                # execute_node_for_instance 返回 dict，需要检查 'continue' 字段
                if isinstance(should_continue, dict):
                    continue_execution = should_continue.get('continue', False)
                else:
                    continue_execution = bool(should_continue)

                if not continue_execution:
                    paused_branches.append({
                        'node_id': node_id,
                        'status': instance.status
                    })
                    continue

                subsequent_ids = next_map.get(node_id, [])
                for sid in subsequent_ids:
                    snode = node_map.get(sid)
                    if snode and sid not in visited:
                        active_nodes.append(snode)

            if paused_branches:
                logger.info(f"[Scheduler] Instance {instance_id} delayed recovery paused {len(paused_branches)} branches")
            elif instance.status == 'running':
                instance.status = 'completed'
                instance.completed_at = datetime.utcnow()
                db.session.commit()

            logger.info(f"[Scheduler] Instance {instance_id} execution completed")

        except Exception as e:
            logger.exception(f"[Scheduler] Error executing delayed node: {e}")
            raise


def schedule_relative_delay(workflow_id, instance_id, node_data, delay_value, delay_unit, recipient_email, mock_send=False):
    """安排相对延时任务（从延迟节点继续执行）"""
    from models import WorkflowInstance

    instance = WorkflowInstance.query.get(instance_id)
    if not instance:
        logger.error(f"[Scheduler] Instance {instance_id} not found")
        return None

    # 使用当前本地时间（与调度器时区一致）
    now = datetime.now()
    if delay_unit == 'minutes':
        run_time = now + timedelta(minutes=delay_value)
    elif delay_unit == 'hours':
        run_time = now + timedelta(hours=delay_value)
    elif delay_unit == 'days':
        run_time = now + timedelta(days=delay_value)
    else:
        logger.error(f"[Scheduler] Unknown delay unit: {delay_unit}")
        return None

    job_id = f"delay_wf{workflow_id}_inst{instance_id}_{int(datetime.now().timestamp())}"

    scheduler.add_job(
        func=execute_delayed_node,
        trigger=DateTrigger(run_date=run_time),
        id=job_id,
        replace_existing=True,
        args=[workflow_id, instance_id, node_data, recipient_email, mock_send]
    )

    logger.info(f"[Scheduler] Scheduled relative delay job: {job_id}, run_time={run_time}")
    return job_id


def schedule_absolute_delay(workflow_id, instance_id, node_data, delay_datetime, recipient_email, mock_send=False):
    """安排绝对时间延时任务"""
    if isinstance(delay_datetime, str):
        try:
            delay_datetime = datetime.fromisoformat(delay_datetime.replace('Z', '+00:00'))
        except:
            logger.error(f"[Scheduler] Failed to parse datetime: {delay_datetime}")
            return None

    # 使用当前本地时间比较
    if delay_datetime <= datetime.now():
        logger.info("[Scheduler] Scheduled time is in the past, executing immediately")
        execute_delayed_node(workflow_id, instance_id, node_data, recipient_email, mock_send)
        return f"immediate_{int(datetime.now().timestamp())}"

    job_id = f"absdelay_wf{workflow_id}_inst{instance_id}_{int(datetime.now().timestamp())}"

    scheduler.add_job(
        func=execute_delayed_node,
        trigger=DateTrigger(run_date=delay_datetime),
        id=job_id,
        replace_existing=True,
        args=[workflow_id, instance_id, node_data, recipient_email, mock_send]
    )

    logger.info(f"[Scheduler] Scheduled absolute delay job: {job_id}, run_time={delay_datetime}")
    return job_id
