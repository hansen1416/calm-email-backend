"""
级联删除工具模块
用于处理移除外键约束后的级联删除逻辑
"""

from models import db, Workflow, WorkflowInstance, NodeExecution, EmailLog, EmailEvent


def delete_workflow_cascade(workflow_id):
    """
    级联删除工作流及其关联数据
    
    删除顺序（避免外键约束，即使有外键也需要按此顺序）：
    1. NodeExecution (节点执行记录)
    2. EmailLog (邮件发送日志)
    3. EmailEvent (邮件事件)
    4. WorkflowInstance (工作流实例)
    5. Workflow (工作流本身)
    
    Args:
        workflow_id: 工作流ID
        
    Returns:
        dict: 删除结果统计
    """
    result = {
        'workflow_id': workflow_id,
        'deleted_node_executions': 0,
        'deleted_email_logs': 0,
        'deleted_email_events': 0,
        'deleted_instances': 0,
        'deleted_workflow': 0,
        'success': True,
        'error': None
    }
    
    try:
        # 1. 获取该工作流的所有实例
        instances = WorkflowInstance.query.filter_by(workflow_id=workflow_id).all()
        instance_ids = [i.id for i in instances]
        
        if instance_ids:
            # 2. 删除 NodeExecution（关联实例）
            result['deleted_node_executions'] = NodeExecution.query.filter(
                NodeExecution.instance_id.in_(instance_ids)
            ).delete(synchronize_session=False)
            
            # 3. 删除 EmailLog（关联实例）
            result['deleted_email_logs'] = EmailLog.query.filter(
                EmailLog.instance_id.in_(instance_ids)
            ).delete(synchronize_session=False)
            
            # 4. 删除 EmailEvent（关联实例）
            result['deleted_email_events'] = EmailEvent.query.filter(
                EmailEvent.instance_id.in_(instance_ids)
            ).delete(synchronize_session=False)
            
            # 5. 删除 WorkflowInstance
            result['deleted_instances'] = WorkflowInstance.query.filter_by(
                workflow_id=workflow_id
            ).delete(synchronize_session=False)
        
        # 6. 删除非实例关联的 EmailLog（直接关联 workflow）
        result['deleted_email_logs'] += EmailLog.query.filter_by(
            workflow_id=workflow_id,
            instance_id=None
        ).delete(synchronize_session=False)
        
        # 7. 删除 Workflow
        result['deleted_workflow'] = Workflow.query.filter_by(
            id=workflow_id
        ).delete(synchronize_session=False)
        
        # 提交事务
        db.session.commit()
        
        print(f"[Cascade Delete] Workflow {workflow_id} and related data deleted:")
        print(f"  - NodeExecutions: {result['deleted_node_executions']}")
        print(f"  - EmailLogs: {result['deleted_email_logs']}")
        print(f"  - EmailEvents: {result['deleted_email_events']}")
        print(f"  - WorkflowInstances: {result['deleted_instances']}")
        print(f"  - Workflow: {result['deleted_workflow']}")
        
    except Exception as e:
        db.session.rollback()
        result['success'] = False
        result['error'] = str(e)
        print(f"[Cascade Delete] Error deleting workflow {workflow_id}: {e}")
        raise
    
    return result


def delete_instance_cascade(instance_id):
    """
    级联删除工作流实例及其关联数据
    
    删除顺序：
    1. NodeExecution
    2. EmailLog
    3. EmailEvent
    4. WorkflowInstance
    
    Args:
        instance_id: 实例ID
        
    Returns:
        dict: 删除结果统计
    """
    result = {
        'instance_id': instance_id,
        'deleted_node_executions': 0,
        'deleted_email_logs': 0,
        'deleted_email_events': 0,
        'deleted_instance': 0,
        'success': True,
        'error': None
    }
    
    try:
        # 1. 删除 NodeExecution
        result['deleted_node_executions'] = NodeExecution.query.filter_by(
            instance_id=instance_id
        ).delete(synchronize_session=False)
        
        # 2. 删除 EmailLog
        result['deleted_email_logs'] = EmailLog.query.filter_by(
            instance_id=instance_id
        ).delete(synchronize_session=False)
        
        # 3. 删除 EmailEvent
        result['deleted_email_events'] = EmailEvent.query.filter_by(
            instance_id=instance_id
        ).delete(synchronize_session=False)
        
        # 4. 删除 WorkflowInstance
        result['deleted_instance'] = WorkflowInstance.query.filter_by(
            id=instance_id
        ).delete(synchronize_session=False)
        
        db.session.commit()
        
        print(f"[Cascade Delete] Instance {instance_id} and related data deleted:")
        print(f"  - NodeExecutions: {result['deleted_node_executions']}")
        print(f"  - EmailLogs: {result['deleted_email_logs']}")
        print(f"  - EmailEvents: {result['deleted_email_events']}")
        print(f"  - Instance: {result['deleted_instance']}")
        
    except Exception as e:
        db.session.rollback()
        result['success'] = False
        result['error'] = str(e)
        print(f"[Cascade Delete] Error deleting instance {instance_id}: {e}")
        raise
    
    return result


def delete_user_cascade(user_id):
    """
    级联删除用户及其所有关联数据
    
    删除顺序：
    1. 删除用户的所有 Workflow -> 级联删除 Workflow 关联数据
    2. 删除用户的 Contact
    3. 删除用户的 ContactGroup
    4. 删除用户的 EmailTemplate
    5. 删除用户本身
    
    Args:
        user_id: 用户ID
        
    Returns:
        dict: 删除结果统计
    """
    result = {
        'user_id': user_id,
        'deleted_workflows': 0,
        'deleted_contacts': 0,
        'deleted_groups': 0,
        'deleted_templates': 0,
        'deleted_user': 0,
        'success': True,
        'error': None
    }
    
    try:
        from models import User, Contact, ContactGroup, EmailTemplate
        
        # 1. 级联删除所有 Workflow
        workflows = Workflow.query.filter_by(user_id=user_id).all()
        for workflow in workflows:
            delete_workflow_cascade(workflow.id)
            result['deleted_workflows'] += 1
        
        # 2. 删除 Contact（注意：需要处理多对多关系）
        # 先解除与组的关联
        contacts = Contact.query.filter_by(user_id=user_id).all()
        for contact in contacts:
            contact.groups = []
        db.session.commit()
        
        result['deleted_contacts'] = Contact.query.filter_by(
            user_id=user_id
        ).delete(synchronize_session=False)
        
        # 3. 删除 ContactGroup
        result['deleted_groups'] = ContactGroup.query.filter_by(
            user_id=user_id
        ).delete(synchronize_session=False)
        
        # 4. 删除 EmailTemplate
        result['deleted_templates'] = EmailTemplate.query.filter_by(
            user_id=user_id
        ).delete(synchronize_session=False)
        
        # 5. 删除独立关联的 EmailLog、EmailEvent、NodeExecution
        EmailLog.query.filter_by(user_id=user_id).delete(synchronize_session=False)
        EmailEvent.query.filter_by(user_id=user_id).delete(synchronize_session=False)
        
        # 6. 删除 User
        result['deleted_user'] = User.query.filter_by(id=user_id).delete(synchronize_session=False)
        
        db.session.commit()
        
        print(f"[Cascade Delete] User {user_id} and related data deleted:")
        print(f"  - Workflows: {result['deleted_workflows']}")
        print(f"  - Contacts: {result['deleted_contacts']}")
        print(f"  - Groups: {result['deleted_groups']}")
        print(f"  - Templates: {result['deleted_templates']}")
        
    except Exception as e:
        db.session.rollback()
        result['success'] = False
        result['error'] = str(e)
        print(f"[Cascade Delete] Error deleting user {user_id}: {e}")
        raise
    
    return result


# 导出主要函数
__all__ = [
    'delete_workflow_cascade',
    'delete_instance_cascade', 
    'delete_user_cascade'
]
