from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

# 用户组与联系人多对多关系
group_contacts = db.Table('group_contacts',
    db.Column('group_id', db.Integer, db.ForeignKey('contact_group.id'), primary_key=True),
    db.Column('contact_id', db.Integer, db.ForeignKey('contact.id'), primary_key=True)
)

class User(db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    email = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Contact(db.Model):
    __tablename__ = 'contact'
    __table_args__ = (
        db.Index('idx_contact_user_id', 'user_id'),
        db.Index('idx_contact_email', 'email'),
    )
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(30), nullable=True)
    company = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    groups = db.relationship('ContactGroup', secondary=group_contacts, back_populates='contacts')

class ContactGroup(db.Model):
    __tablename__ = 'contact_group'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    contacts = db.relationship('Contact', secondary=group_contacts, back_populates='groups')

class EmailTemplate(db.Model):
    __tablename__ = 'email_template'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class WorkflowInstance(db.Model):
    """工作流执行实例 - 每封邮件对应一个实例"""
    __tablename__ = 'workflow_instance'
    __table_args__ = (
        db.Index('idx_instance_workflow_id', 'workflow_id'),
        db.Index('idx_instance_user_id', 'user_id'),
        db.Index('idx_instance_status', 'status'),
        db.Index('idx_instance_message_id', 'message_id'),
        db.Index('idx_instance_created_at', 'created_at'),
    )
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    workflow_id = db.Column(db.Integer, db.ForeignKey('workflow.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # 关联信息
    recipient_email = db.Column(db.String(120), nullable=False)  # 收件人
    message_id = db.Column(db.String(100), nullable=True)  # SES Message ID
    
    # 执行状态
    status = db.Column(db.String(20), default='pending')  # pending/running/waiting_event/delayed/completed/failed/cancelled
    current_node_id = db.Column(db.String(50), nullable=True)  # 当前执行到的节点
    
    # Driver 节点等待状态
    waiting_event_type = db.Column(db.String(20), nullable=True)  # click/open/delivery/bounce/etc
    waiting_conditions = db.Column(db.JSON, nullable=True)  # {field, operator, value}
    waiting_since = db.Column(db.DateTime, nullable=True)  # 开始等待的时间
    
    # 执行上下文（传递变量）
    context = db.Column(db.JSON, nullable=True)  # {template_id, contact_ids, group_ids, ...}
    
    # 时间戳
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    
    # 关系
    email_logs = db.relationship('EmailLog', backref='instance', lazy=True)
    node_executions = db.relationship('NodeExecution', backref='instance', lazy=True, cascade='all, delete-orphan', order_by='desc(NodeExecution.executed_at)')


class EmailLog(db.Model):
    __tablename__ = 'email_log'
    __table_args__ = (
        db.Index('idx_emaillog_user_id', 'user_id'),
        db.Index('idx_emaillog_instance_id', 'instance_id'),
        db.Index('idx_emaillog_message_id', 'message_id'),
        db.Index('idx_emaillog_sent_at', 'sent_at'),
    )
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    template_id = db.Column(db.Integer, db.ForeignKey('email_template.id'), nullable=True)
    workflow_id = db.Column(db.Integer, db.ForeignKey('workflow.id'), nullable=True)
    instance_id = db.Column(db.Integer, db.ForeignKey('workflow_instance.id'), nullable=True)  # 关联到实例
    node_id = db.Column(db.String(50), nullable=True)
    source_event_id = db.Column(db.Integer, db.ForeignKey('email_event.id'), nullable=True)
    recipient_email = db.Column(db.String(120), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    message_id = db.Column(db.String(100), nullable=True)
    status = db.Column(db.String(20), default='sent')
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)

class Workflow(db.Model):
    __tablename__ = 'workflow'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    flow_data = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='inactive')  # active/inactive
    execution_mode = db.Column(db.String(20), default='manual')  # manual/auto
    start_time = db.Column(db.DateTime, nullable=True)  # 定时执行时间
    last_executed_at = db.Column(db.DateTime, nullable=True)  # 最后执行时间
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关系
    instances = db.relationship('WorkflowInstance', backref='workflow', lazy=True, cascade='all, delete-orphan')

class EmailEvent(db.Model):
    __tablename__ = 'email_event'
    __table_args__ = (
        db.Index('idx_emailevent_message_id', 'message_id'),
        db.Index('idx_emailevent_event_type', 'event_type'),
        db.Index('idx_emailevent_created_at', 'created_at'),
    )
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    instance_id = db.Column(db.Integer, db.ForeignKey('workflow_instance.id'), nullable=True)  # 关联到实例
    message_id = db.Column(db.String(100), nullable=True)
    event_type = db.Column(db.String(20), nullable=False)
    recipient_email = db.Column(db.String(120), nullable=False)
    event_data = db.Column(db.JSON, nullable=True)
    occurred_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# __repr__ 方法便于调试
User.__repr__ = lambda self: f'<User {self.username}>'
Contact.__repr__ = lambda self: f'<Contact {self.email}>'
ContactGroup.__repr__ = lambda self: f'<Group {self.name}>'
EmailTemplate.__repr__ = lambda self: f'<Template {self.name}>'
Workflow.__repr__ = lambda self: f'<Workflow {self.name}>'
WorkflowInstance.__repr__ = lambda self: f'<Instance {self.id} {self.recipient_email} {self.status}>'
EmailLog.__repr__ = lambda self: f'<EmailLog {self.recipient_email}>'
EmailEvent.__repr__ = lambda self: f'<EmailEvent {self.event_type} {self.recipient_email}>'


class NodeExecution(db.Model):
    """节点执行记录 - 记录每个节点的执行历史"""
    __tablename__ = 'node_execution'
    __table_args__ = (
        db.Index('idx_nodeexecution_instance_id', 'instance_id'),
        db.Index('idx_nodeexecution_node_id', 'node_id'),
        db.Index('idx_nodeexecution_result', 'result'),
        db.Index('idx_nodeexecution_executed_at', 'executed_at'),
    )
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    instance_id = db.Column(db.Integer, db.ForeignKey('workflow_instance.id'), nullable=False)
    node_id = db.Column(db.String(50), nullable=False)  # 节点ID
    node_type = db.Column(db.String(20), nullable=False)  # email/driver/delay/condition
    node_label = db.Column(db.String(100), nullable=True)  # 节点名称

    # 执行结果
    result = db.Column(db.String(20), nullable=False)  # success/waiting/resumed/failed/skipped

    # 输入数据（节点配置）
    input_data = db.Column(db.JSON, nullable=True)  # {template_id, subject, ...}

    # 输出数据（执行结果）
    output_data = db.Column(db.JSON, nullable=True)  # {message_id, status, ...}

    # 恢复相关（仅 driver 节点）
    resumed_by_event_id = db.Column(db.Integer, db.ForeignKey('email_event.id'), nullable=True)
    event_data = db.Column(db.JSON, nullable=True)  # 触发恢复的事件数据
    conditions_met = db.Column(db.Boolean, nullable=True)  # 条件是否满足

    # 错误信息
    error_message = db.Column(db.Text, nullable=True)

    # 执行时间
    executed_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)  # 完成时间（对于waiting节点是恢复时间）

    # 耗时（毫秒）
    duration_ms = db.Column(db.Integer, nullable=True)


NodeExecution.__repr__ = lambda self: f'<NodeExecution {self.node_type} {self.node_id} {self.result}>'