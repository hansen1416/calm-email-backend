import json
from datetime import datetime, timedelta
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from flask_apscheduler import APScheduler
from models import db, Workflow, WorkflowInstance, EmailTemplate, EmailLog, Contact, ContactGroup
from routes.email import send_email

scheduler = APScheduler()


def init_scheduler(app):
    """初始化调度器，配置数据库存储"""
    # 先配置调度器参数
    app.config['SCHEDULER_API_ENABLED'] = True
    app.config['SCHEDULER_TIMEZONE'] = 'UTC'

    try:
        # 延迟导入 SQLAlchemyJobStore 避免循环导入
        from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

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
            'coalesce': True,  # 合并错过的任务
            'max_instances': 1,  # 每个任务只允许一个实例运行
            'misfire_grace_time': 3600  # 允许1小时的容错时间
        }

        print("[Scheduler] Using SQLAlchemyJobStore for persistence")
        print("[Scheduler] Jobs table: apscheduler_jobs")
    except Exception as e:
        print(f"[Scheduler] Failed to use SQLAlchemyJobStore: {e}")
        print("[Scheduler] Using default memory store (jobs will be lost on restart)")

    scheduler.init_app(app)
    scheduler.start()
    print("[Scheduler] Scheduler started successfully")


def shutdown_scheduler():
    """优雅关闭调度器"""
    if scheduler.running:
        scheduler.shutdown(wait=True)
        print("[Scheduler] Scheduler shutdown")


def execute_scheduled_workflow(workflow_id, mock_send=False):
    """定时执行工作流
    
    Args:
        workflow_id: 工作流ID
        mock_send: 是否模拟发送
    """
    from app import create_app
    from routes.workflow import execute_workflow
    
    app = create_app()
    
    with app.app_context():
        print(f"[Scheduler] Executing scheduled workflow {workflow_id}")
        
        # 模拟请求上下文
        with app.test_client() as client:
            import json
            
            # 注意：实际实现需要找到工作流并执行
            # 这里简化处理，真实场景需要用户认证
            workflow = Workflow.query.get(workflow_id)
            if not workflow:
                print(f"[Scheduler] Workflow {workflow_id} not found")
                return
            
            if workflow.status != 'active':
                print(f"[Scheduler] Workflow {workflow_id} is not active")
                return
            
            print(f"[Scheduler] Triggering workflow execution for {workflow.name}")
            
            # 通过 HTTP API 调用
            # 注意：需要解决 JWT 认证问题
            # 实际生产环境建议使用内部调用或直接执行逻辑


def execute_delayed_node(workflow_id, instance_id, node_data, recipient_email, mock_send=False):
    """执行延时节点后的邮件发送
    
    恢复实例执行，继续后续节点
    """
    from app import create_app
    app = create_app()

    with app.app_context():
        # 获取实例
        instance = WorkflowInstance.query.get(instance_id)
        if not instance:
            print(f"[Scheduler] Instance {instance_id} not found")
            return
        
        if instance.status != 'delayed':
            print(f"[Scheduler] Instance {instance_id} status is {instance.status}, expected 'delayed'")
            return
        
        print(f"[Scheduler] Resuming delayed instance {instance_id}")
        
        # 更新状态为 running
        instance.status = 'running'
        db.session.commit()
        
        # 获取工作流
        workflow = Workflow.query.get(workflow_id)
        if not workflow:
            print(f"[Scheduler] Workflow {workflow_id} not found")
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
        
        # 找到延时节点的后续节点
        current_node_id = instance.current_node_id
        if not current_node_id:
            print(f"[Scheduler] No current_node_id for instance {instance_id}")
            return
        
        next_ids = next_map.get(current_node_id, [])
        if not next_ids:
            # 没有后续节点，标记完成
            instance.status = 'completed'
            instance.completed_at = datetime.utcnow()
            db.session.commit()
            print(f"[Scheduler] Instance {instance_id} completed (no more nodes)")
            return
        
# 执行后续节点 - 支持并行路径
        from routes.workflow import execute_node_for_instance

        active_nodes = []
        for next_id in next_ids:
            next_node = node_map.get(next_id)
            if next_node:
                active_nodes.append(next_node)

        # 遍历所有活跃节点（支持并行分支）
        visited = set([current_node_id])
        paused_branches = []

        while active_nodes:
            node = active_nodes.pop(0)
            node_id = node.get('id')

            if node_id in visited:
                continue
            visited.add(node_id)

            # 执行节点
            should_continue = execute_node_for_instance(
                instance, node, node_map, next_map,
                workflow.user_id, mock_send
            )

            if not should_continue:
                # 节点暂停，记录但不停止其他分支
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
            print(f"[Scheduler] Instance {instance_id} delayed recovery paused {len(paused_branches)} branches")
        elif instance.status == 'running':
            instance.status = 'completed'
            instance.completed_at = datetime.utcnow()
            db.session.commit()

        print(f"[Scheduler] Instance {instance_id} execution completed with status: {instance.status}")


def schedule_relative_delay(workflow_id, instance_id, node_data, delay_value, delay_unit, recipient_email, mock_send=False):
    """安排相对延时任务（从延迟节点继续执行）"""
    from models import WorkflowInstance

    # 获取实例以获取当前节点ID
    instance = WorkflowInstance.query.get(instance_id)
    if not instance:
        print(f"[Scheduler] Instance {instance_id} not found")
        return None

    # 计算延时时间
    delay_seconds = delay_value
    if delay_unit == 'minutes':
        delay_seconds = delay_value * 60
    elif delay_unit == 'hours':
        delay_seconds = delay_value * 3600
    elif delay_unit == 'days':
        delay_seconds = delay_value * 86400

    run_date = datetime.now() + timedelta(seconds=delay_seconds)

    # 使用更稳定的 job_id 格式
    job_id = f"delay_wf{workflow_id}_inst{instance_id}_{int(run_date.timestamp())}"

    scheduler.add_job(
        id=job_id,
        func=execute_delayed_node,
        trigger=DateTrigger(run_date=run_date),
        args=[workflow_id, instance_id, node_data, recipient_email, mock_send],
        name=f"Delay: Workflow {workflow_id} Instance {instance_id}",
        replace_existing=True  # 如果存在相同ID的任务则替换
    )

    print(f"[Scheduler] Scheduled relative delay: {delay_value} {delay_unit}")
    print(f"  Job ID: {job_id}")
    print(f"  Will run at: {run_date}")

    return job_id


def schedule_absolute_delay(workflow_id, instance_id, node_data, delay_datetime_str, recipient_email, mock_send=False):
    """安排绝对延时任务（指定日期时间）"""
    from models import WorkflowInstance

    try:
        run_date = datetime.fromisoformat(delay_datetime_str.replace('Z', '+00:00'))
    except:
        try:
            run_date = datetime.strptime(delay_datetime_str, '%Y-%m-%dT%H:%M')
        except:
            print(f"[Scheduler] Invalid datetime format: {delay_datetime_str}")
            return None

    if run_date <= datetime.now():
        print(f"[Scheduler] Scheduled time is in the past, executing immediately")
        execute_delayed_node(workflow_id, instance_id, node_data, recipient_email, mock_send)
        return None

    # 获取实例以获取当前节点ID
    instance = WorkflowInstance.query.get(instance_id)
    if not instance:
        print(f"[Scheduler] Instance {instance_id} not found")
        return None

    job_id = f"absdelay_wf{workflow_id}_inst{instance_id}_{int(run_date.timestamp())}"

    scheduler.add_job(
        id=job_id,
        func=execute_delayed_node,
        trigger=DateTrigger(run_date=run_date),
        args=[workflow_id, instance_id, node_data, recipient_email, mock_send],
        name=f"AbsDelay: Workflow {workflow_id} Instance {instance_id}",
        replace_existing=True
    )

    print(f"[Scheduler] Scheduled absolute delay: {delay_datetime_str}")
    print(f"  Job ID: {job_id}")
    print(f"  Will run at: {run_date}")

    return job_id


def cancel_scheduled_job(job_id):
    """取消预定的延时任务"""
    try:
        scheduler.remove_job(job_id)
        print(f"[Scheduler] Cancelled job: {job_id}")
        return True
    except:
        print(f"[Scheduler] Job not found: {job_id}")
        return False


def get_scheduled_jobs():
    """获取所有预定的延时任务"""
    jobs = scheduler.get_jobs()
    return [
        {
            'id': job.id,
            'name': job.name,
            'next_run_time': job.next_run_time.strftime('%Y-%m-%d %H:%M:%S') if job.next_run_time else None
        }
        for job in jobs
    ]