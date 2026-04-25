from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

# 用户组与联系人多对多关系表（无外键约束）
group_contacts = db.Table(
    'group_contacts',
    db.Column('group_id', db.Integer, primary_key=True, comment='用户组ID'),
    db.Column('contact_id', db.Integer, primary_key=True, comment='联系人ID')
)


class User(db.Model):
    """用户表 - 存储系统用户信息"""
    __tablename__ = 'user'
    __table_args__ = {'comment': '用户表 - 存储系统用户信息'}

    id = db.Column(db.Integer, primary_key=True, autoincrement=True,
                   comment='用户ID，主键自增')
    username = db.Column(db.String(80), unique=True, nullable=False,
                         comment='用户名，唯一')
    password_hash = db.Column(db.String(256), nullable=False,
                              comment='密码哈希值')
    email = db.Column(db.String(120), nullable=True,
                      comment='用户邮箱，可选')
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           comment='创建时间')

    def set_password(self, password):
        """设置密码"""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """验证密码"""
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'


class Contact(db.Model):
    """联系人表 - 存储用户联系人信息"""
    __tablename__ = 'contact'
    __table_args__ = (
        db.Index('idx_contact_user_id', 'user_id'),
        db.Index('idx_contact_email', 'email'),
        {'comment': '联系人表 - 存储用户联系人信息'}
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True,
                   comment='联系人ID，主键自增')
    user_id = db.Column(db.Integer, nullable=False,
                        comment='所属用户ID')
    name = db.Column(db.String(100), nullable=False,
                     comment='联系人姓名')
    email = db.Column(db.String(120), nullable=False,
                      comment='联系人邮箱')
    phone = db.Column(db.String(30), nullable=True,
                      comment='联系人电话')
    company = db.Column(db.String(100), nullable=True,
                       comment='联系人公司')
    notes = db.Column(db.Text, nullable=True,
                      comment='备注信息')
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           comment='创建时间')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow,
                           comment='更新时间')

    def __repr__(self):
        return f'<Contact {self.email}>'

    def get_group_ids(self):
        """获取联系人所属的组ID列表"""
        from sqlalchemy import text
        result = db.session.execute(
            text("SELECT group_id FROM group_contacts WHERE contact_id = :cid"),
            {"cid": self.id}
        )
        return [row[0] for row in result]

    def get_groups(self):
        """获取联系人所属的所有组"""
        group_ids = self.get_group_ids()
        if not group_ids:
            return []
        return ContactGroup.query.filter(ContactGroup.id.in_(group_ids)).all()


class ContactGroup(db.Model):
    """联系人组表 - 存储用户联系人分组信息"""
    __tablename__ = 'contact_group'
    __table_args__ = {'comment': '联系人组表 - 存储用户联系人分组信息'}

    id = db.Column(db.Integer, primary_key=True, autoincrement=True,
                   comment='组ID，主键自增')
    user_id = db.Column(db.Integer, nullable=False,
                        comment='所属用户ID')
    name = db.Column(db.String(100), nullable=False,
                     comment='组名称')
    description = db.Column(db.String(255), nullable=True,
                             comment='组描述')
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           comment='创建时间')

    def __repr__(self):
        return f'<Group {self.name}>'

    def get_contact_ids(self):
        """获取组内所有联系人ID列表"""
        from sqlalchemy import text
        result = db.session.execute(
            text("SELECT contact_id FROM group_contacts WHERE group_id = :gid"),
            {"gid": self.id}
        )
        return [row[0] for row in result]

    def get_contacts(self):
        """获取组内的所有联系人"""
        contact_ids = self.get_contact_ids()
        if not contact_ids:
            return []
        return Contact.query.filter(Contact.id.in_(contact_ids)).all()

    def add_contact(self, contact_id):
        """添加联系人到组"""
        from sqlalchemy import text
        try:
            db.session.execute(
                text("INSERT INTO group_contacts (group_id, contact_id) VALUES (:gid, :cid)"),
                {"gid": self.id, "cid": contact_id}
            )
            db.session.commit()
            return True
        except Exception:
            db.session.rollback()
            return False

    def remove_contact(self, contact_id):
        """从组中移除联系人"""
        from sqlalchemy import text
        db.session.execute(
            text("DELETE FROM group_contacts WHERE group_id = :gid AND contact_id = :cid"),
            {"gid": self.id, "cid": contact_id}
        )
        db.session.commit()

    def has_contact(self, contact_id):
        """检查组中是否包含指定联系人"""
        from sqlalchemy import text
        result = db.session.execute(
            text("SELECT 1 FROM group_contacts WHERE group_id = :gid AND contact_id = :cid LIMIT 1"),
            {"gid": self.id, "cid": contact_id}
        )
        return result.fetchone() is not None


class EmailTemplate(db.Model):
    """邮件模板表 - 存储用户邮件模板"""
    __tablename__ = 'email_template'
    __table_args__ = {'comment': '邮件模板表 - 存储用户邮件模板'}

    id = db.Column(db.Integer, primary_key=True, autoincrement=True,
                   comment='模板ID，主键自增')
    user_id = db.Column(db.Integer, nullable=False,
                        comment='所属用户ID')
    name = db.Column(db.String(100), nullable=False,
                     comment='模板名称')
    subject = db.Column(db.String(255), nullable=False,
                         comment='邮件主题')
    body = db.Column(db.Text, nullable=False,
                     comment='邮件正文（支持HTML）')
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           comment='创建时间')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow,
                           comment='更新时间')

    def __repr__(self):
        return f'<Template {self.name}>'


class Workflow(db.Model):
    """工作流表 - 存储工作流定义"""
    __tablename__ = 'workflow'
    __table_args__ = {'comment': '工作流表 - 存储工作流定义'}

    id = db.Column(db.Integer, primary_key=True, autoincrement=True,
                   comment='工作流ID，主键自增')
    user_id = db.Column(db.Integer, nullable=False,
                        comment='所属用户ID')
    name = db.Column(db.String(100), nullable=False,
                     comment='工作流名称')
    flow_data = db.Column(db.Text, nullable=False,
                          comment='工作流数据（JSON格式，包含nodes和edges）')
    status = db.Column(db.String(20), default='inactive',
                       comment='工作流状态：active-激活，inactive-未激活')
    execution_mode = db.Column(db.String(20), default='manual',
                               comment='执行模式：manual-手动，auto-定时')
    start_time = db.Column(db.DateTime, nullable=True,
                           comment='定时执行时间（仅execution_mode=auto时使用）')
    last_executed_at = db.Column(db.DateTime, nullable=True,
                                 comment='最后执行时间')
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           comment='创建时间')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow,
                           comment='更新时间')

    # 关系 - 使用 primaryjoin 明确指定关联条件
    instances = db.relationship('WorkflowInstance',
                                  primaryjoin='Workflow.id == WorkflowInstance.workflow_id',
                                  foreign_keys='WorkflowInstance.workflow_id',
                                  backref='workflow', lazy=True)

    def __repr__(self):
        return f'<Workflow {self.name}>'


class WorkflowInstance(db.Model):
    """工作流实例表 - 记录每个工作流执行实例"""
    __tablename__ = 'workflow_instance'
    __table_args__ = (
        db.Index('idx_instance_workflow_id', 'workflow_id'),
        db.Index('idx_instance_user_id', 'user_id'),
        db.Index('idx_instance_status', 'status'),
        db.Index('idx_instance_message_id', 'message_id'),
        db.Index('idx_instance_created_at', 'created_at'),
        {'comment': '工作流实例表 - 记录每个工作流执行实例（每个收件人对应一个实例）'}
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True,
                   comment='实例ID，主键自增')
    workflow_id = db.Column(db.Integer, nullable=False,
                            comment='工作流ID')
    user_id = db.Column(db.Integer, nullable=False,
                        comment='用户ID')

    # 关联信息
    recipient_email = db.Column(db.String(120), nullable=False,
                                comment='收件人邮箱')
    message_id = db.Column(db.String(100), nullable=True,
                           comment='AWS SES Message ID（首封邮件的Message ID）')

    # 执行状态
    status = db.Column(db.String(20), default='pending',
                       comment='实例状态：pending-待执行，running-运行中，waiting_event-等待事件，delayed-已延时，completed-已完成，failed-失败，cancelled-已取消')
    current_node_id = db.Column(db.String(50), nullable=True,
                                comment='当前执行到的节点ID')

    # Driver 节点等待状态
    waiting_event_type = db.Column(db.String(20), nullable=True,
                                   comment='等待的事件类型：open/click/delivery/bounce/complaint等')
    waiting_conditions = db.Column(db.JSON, nullable=True,
                                   comment='等待条件配置（JSON格式：{field, operator, value}）')
    waiting_since = db.Column(db.DateTime, nullable=True,
                              comment='开始等待的时间')

    # 执行上下文（传递变量）
    context = db.Column(db.JSON, nullable=True,
                        comment='执行上下文（JSON格式，存储template_id, contact_ids等）')

    # 时间戳
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           comment='创建时间')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow,
                           comment='更新时间')
    completed_at = db.Column(db.DateTime, nullable=True,
                             comment='完成时间')

    # 关系 - 使用 primaryjoin 明确指定关联条件
    email_logs = db.relationship('EmailLog',
                                 primaryjoin='WorkflowInstance.id == EmailLog.instance_id',
                                 foreign_keys='EmailLog.instance_id',
                                 backref='instance', lazy=True)
    node_executions = db.relationship('NodeExecution',
                                        primaryjoin='WorkflowInstance.id == NodeExecution.instance_id',
                                        foreign_keys='NodeExecution.instance_id',
                                        backref='instance', lazy=True,
                                        order_by='desc(NodeExecution.executed_at)')

    def __repr__(self):
        return f'<Instance {self.id} {self.recipient_email} {self.status}>'


class EmailLog(db.Model):
    """邮件发送日志表 - 记录每封已发送的邮件"""
    __tablename__ = 'email_log'
    __table_args__ = (
        db.Index('idx_emaillog_user_id', 'user_id'),
        db.Index('idx_emaillog_instance_id', 'instance_id'),
        db.Index('idx_emaillog_message_id', 'message_id'),
        db.Index('idx_emaillog_sent_at', 'sent_at'),
        {'comment': '邮件发送日志表 - 记录每封已发送的邮件'}
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True,
                   comment='日志ID，主键自增')
    user_id = db.Column(db.Integer, nullable=False,
                        comment='用户ID')
    template_id = db.Column(db.Integer, nullable=True,
                            comment='邮件模板ID')
    workflow_id = db.Column(db.Integer, nullable=True,
                            comment='工作流ID')
    instance_id = db.Column(db.Integer, nullable=True,
                            comment='工作流实例ID')
    node_id = db.Column(db.String(50), nullable=True,
                        comment='节点ID（工作流中的节点）')
    source_event_id = db.Column(db.Integer, nullable=True,
                                comment='触发此邮件的事件ID（事件驱动场景）')
    recipient_email = db.Column(db.String(120), nullable=False,
                                comment='收件人邮箱')
    subject = db.Column(db.String(255), nullable=False,
                        comment='邮件主题')
    message_id = db.Column(db.String(100), nullable=True,
                             comment='AWS SES Message ID')
    status = db.Column(db.String(20), default='sent',
                       comment='发送状态：sent-已发送，failed-发送失败，bounced-退信，complained-投诉')
    # M4: 发件绑定信息（代码层面关联 user_sender_binding 表）
    sender_binding_id = db.Column(db.Integer, nullable=True,
                                  comment='关联的发件邮箱绑定ID')
    sender_email_type = db.Column(db.String(20), nullable=True,
                                  comment='发件类型: personal/system/system_default')
    reply_to_email = db.Column(db.String(120), nullable=True,
                               comment='Reply-To 邮箱地址（系统模式下发件人回复地址）')
    sent_at = db.Column(db.DateTime, default=datetime.utcnow,
                        comment='发送时间')

    def __repr__(self):
        return f'<EmailLog {self.recipient_email}>'


class EmailEvent(db.Model):
    """邮件事件表 - 记录AWS SES推送的邮件事件（打开、点击等）"""
    __tablename__ = 'email_event'
    __table_args__ = (
        db.Index('idx_emailevent_message_id', 'message_id'),
        db.Index('idx_emailevent_event_type', 'event_type'),
        db.Index('idx_emailevent_created_at', 'created_at'),
        {'comment': '邮件事件表 - 记录AWS SES推送的邮件事件（打开、点击等）'}
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True,
                   comment='事件ID，主键自增')
    user_id = db.Column(db.Integer, nullable=False,
                        comment='用户ID')
    instance_id = db.Column(db.Integer, nullable=True,
                            comment='关联的工作流实例ID')
    message_id = db.Column(db.String(100), nullable=True,
                           comment='关联的邮件Message ID')
    event_type = db.Column(db.String(20), nullable=False,
                           comment='事件类型：send/delivery/open/click/bounce/complaint等')
    recipient_email = db.Column(db.String(120), nullable=False,
                                comment='收件人邮箱')
    event_data = db.Column(db.JSON, nullable=True,
                           comment='事件原始数据（JSON格式）')
    source_email_log_id = db.Column(db.Integer, nullable=True,
    comment='来源邮件日志ID，指向触发此事件的原始邮件')
    occurred_at = db.Column(db.DateTime, nullable=True,
                           comment='事件发生时间（来自AWS SNS）')
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           comment='记录创建时间')

    # SNS 消息去重和延迟监控
    sns_message_id = db.Column(db.String(100), nullable=True, unique=True,
                               comment='SNS 消息唯一ID，用于去重')
    sns_received_at = db.Column(db.DateTime, nullable=True,
                               comment='SNS 消息接收时间，用于计算回调延迟')
    sns_delay_seconds = db.Column(db.Float, nullable=True,
                                  comment='SNS 回调延迟秒数（sns_received_at - sent_at）')

    def __repr__(self):
        return f'<EmailEvent {self.event_type} {self.recipient_email}>'


class NodeExecution(db.Model):
    """节点执行记录表 - 记录工作流中每个节点的执行历史"""
    __tablename__ = 'node_execution'
    __table_args__ = (
        db.Index('idx_nodeexecution_instance_id', 'instance_id'),
        db.Index('idx_nodeexecution_node_id', 'node_id'),
        db.Index('idx_nodeexecution_result', 'result'),
        db.Index('idx_nodeexecution_executed_at', 'executed_at'),
        {'comment': '节点执行记录表 - 记录工作流中每个节点的执行历史'}
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True,
                   comment='执行记录ID，主键自增')
    instance_id = db.Column(db.Integer, nullable=False,
                            comment='工作流实例ID')
    node_id = db.Column(db.String(50), nullable=False,
                        comment='节点ID')
    node_type = db.Column(db.String(20), nullable=False,
                          comment='节点类型：email-邮件节点，driver-事件驱动节点，delay-延时节点，condition-条件节点')
    node_label = db.Column(db.String(100), nullable=True,
                           comment='节点显示名称')

    # 执行结果
    result = db.Column(db.String(20), nullable=False,
                       comment='执行结果：running-执行中，success-成功，waiting-等待中（driver/delay节点），resumed-已恢复，failed-失败，skipped-跳过')

    # 输入数据（节点配置）
    input_data = db.Column(db.JSON, nullable=True,
                           comment='节点输入数据（JSON格式，包含template_id等配置）')

    # 输出数据（执行结果）
    output_data = db.Column(db.JSON, nullable=True,
                            comment='节点输出数据（JSON格式，包含message_id, sent_count等结果）')

    # 恢复相关（仅 driver 节点）
    resumed_by_event_id = db.Column(db.Integer, nullable=True,
                                    comment='恢复此节点执行的事件ID（仅driver节点）')
    event_data = db.Column(db.JSON, nullable=True,
                           comment='触发恢复的事件数据（仅driver节点）')
    conditions_met = db.Column(db.Boolean, nullable=True,
                               comment='条件是否满足（仅driver/condition节点）')

    # 错误信息
    error_message = db.Column(db.Text, nullable=True,
                              comment='错误信息（执行失败时记录）')

    # 执行时间
    executed_at = db.Column(db.DateTime, default=datetime.utcnow,
                            comment='开始执行时间')
    completed_at = db.Column(db.DateTime, nullable=True,
                             comment='完成时间（对于waiting节点是恢复时间）')

    # 耗时（毫秒）
    duration_ms = db.Column(db.Integer, nullable=True,
                            comment='执行耗时（毫秒）')

    def __repr__(self):
        return f'<NodeExecution {self.node_type} {self.node_id} {self.result}>'


# ==================== M1: 用户邮箱白名单功能数据模型 ====================

class EmailQuotaConfig(db.Model):
    """配额配置模板 - 支持差异化配额"""
    __tablename__ = 'email_quota_config'
    __table_args__ = {'comment': '配额配置模板 - 支持差异化配额'}
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True,
                   comment='配置ID，主键自增')
    name = db.Column(db.String(50), nullable=False,
                     comment='配置名称：free/basic/premium')
    daily_limit = db.Column(db.Integer, default=100,
                            comment='每日发送限制')
    description = db.Column(db.String(255), nullable=True,
                            comment='配置描述')
    is_default = db.Column(db.Boolean, default=False,
                           comment='是否默认配置')
    # 预留价格字段（购买升级功能）
    price_monthly = db.Column(db.Integer, nullable=True,
                              comment='月付价格（分）')
    price_yearly = db.Column(db.Integer, nullable=True,
                             comment='年付价格（分）')
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           comment='创建时间')

    def __repr__(self):
        return f'<EmailQuotaConfig {self.name} {self.daily_limit}/day>'


class UserSenderBinding(db.Model):
    """用户发件邮箱绑定 - 白名单核心表"""
    __tablename__ = 'user_sender_binding'
    __table_args__ = (
        db.Index('idx_usb_user_id', 'user_id'),
        db.Index('idx_usb_email', 'email'),
        db.Index('idx_usb_email_type', 'email_type'),
        {'comment': '用户发件邮箱绑定 - 白名单核心表'}
    )
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True,
                   comment='绑定ID，主键自增')
    user_id = db.Column(db.Integer, nullable=False,
                        comment='所属用户ID（代码层面关联user表）')
    
    # 核心字段：支持两种模式
    email = db.Column(db.String(120), nullable=False,
                     comment='实际发件地址')
    email_type = db.Column(db.String(20), default='personal',
                           comment='邮箱类型：personal-用户自己邮箱, system-系统子邮箱')
    
    # SES验证状态
    ses_identity_status = db.Column(db.String(20), default='pending',
                                    comment='SES身份验证状态：pending/verified/failed')
    ses_verified_at = db.Column(db.DateTime, nullable=True,
                                comment='SES验证通过时间')
    
    # 个人邮箱验证Token（personal模式使用）
    verification_token = db.Column(db.String(6), nullable=True,
                                   comment='6位验证码')
    token_expires_at = db.Column(db.DateTime, nullable=True,
                                 comment='验证码过期时间')
    
    # 系统模式：关联真实邮箱（用于Reply-To和通知）
    real_email = db.Column(db.String(120), nullable=True,
                           comment='用户真实邮箱（用于Reply-To和通知）')
    
    # 配额（quota_config_id代码层面关联quota_config表）
    quota_config_id = db.Column(db.Integer, nullable=True,
                                comment='关联的配额配置ID')
    custom_daily_limit = db.Column(db.Integer, nullable=True,
                                  comment='个性化每日配额（覆盖默认）')
    
    # 使用统计（每日重置）
    daily_sent = db.Column(db.Integer, default=0,
                           comment='今日已发送数量')
    daily_reset_at = db.Column(db.DateTime, nullable=True,
                               comment='配额重置时间')
    
    is_default = db.Column(db.Boolean, default=False,
                         comment='是否默认发件邮箱')
    is_active = db.Column(db.Boolean, default=True,
                          comment='是否启用')
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           comment='创建时间')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow,
                           comment='更新时间')

    def __repr__(self):
        return f'<UserSenderBinding {self.email} ({self.email_type})>'


class UserSubscription(db.Model):
    """用户订阅/购买记录（预留 - 购买升级功能）"""
    __tablename__ = 'user_subscription'
    __table_args__ = (
        db.Index('idx_sub_user_id', 'user_id'),
        {'comment': '用户订阅/购买记录（预留 - 购买升级功能）'}
    )
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True,
                   comment='订阅ID，主键自增')
    user_id = db.Column(db.Integer, nullable=False,
                        comment='用户ID')
    quota_config_id = db.Column(db.Integer, nullable=False,
                               comment='购买的配额配置ID')
    
    # 支付信息（预留多支付服务商）
    payment_provider = db.Column(db.String(20), nullable=True,
                                comment='支付服务商：alipay/wechat/stripe')
    payment_order_id = db.Column(db.String(100), nullable=True,
                                comment='支付服务商订单号')
    amount_paid = db.Column(db.Integer, nullable=True,
                           comment='实际支付金额（分）')
    
    status = db.Column(db.String(20), default='pending',
                      comment='订阅状态：pending/paid/cancelled/expired')
    
    started_at = db.Column(db.DateTime, nullable=True,
                          comment='订阅开始时间')
    expires_at = db.Column(db.DateTime, nullable=True,
                          comment='订阅过期时间')
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           comment='创建时间')

    def __repr__(self):
        return f'<UserSubscription {self.user_id} {self.status}>'


class Notification(db.Model):
    """系统通知 - 用于回复通知、系统消息等"""
    __tablename__ = 'notification'
    __table_args__ = (
        db.Index('idx_notif_user_id', 'user_id'),
        db.Index('idx_notif_type', 'type'),
        db.Index('idx_notif_created_at', 'created_at'),
        {'comment': '系统通知 - 用于回复通知、系统消息等'}
    )
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True,
                   comment='通知ID，主键自增')
    user_id = db.Column(db.Integer, nullable=False,
                        comment='用户ID')
    type = db.Column(db.String(50), nullable=False,
                    comment='通知类型：email_reply/quota_warning/migration_notice/system')
    title = db.Column(db.String(200), nullable=False,
                     comment='通知标题')
    content = db.Column(db.Text, nullable=True,
                       comment='通知内容')
    
    is_read = db.Column(db.Boolean, default=False,
                       comment='是否已读')
    
    # 关联数据（JSON格式，存储相关ID等）
    related_data = db.Column(db.JSON, nullable=True,
                            comment='关联数据：如邮件ID、绑定ID等')
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           comment='创建时间')
    read_at = db.Column(db.DateTime, nullable=True,
                       comment='阅读时间')

    def __repr__(self):
        return f'<Notification {self.type} {self.title[:20]}>'
