from flask import Flask, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager, jwt_required, get_jwt_identity
from config import Config
from models import db
import logging
import sys
import os
from datetime import datetime

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # 手动配置 SQLAlchemy 引擎选项 - 必须在 db.init_app 之前设置
    # 这些选项会覆盖 config.py 中的 SQLALCHEMY_ENGINE_OPTIONS
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,        # 使用前 ping 检查连接是否有效
        'pool_recycle': 280,          # 280秒回收连接（小于MySQL默认wait_timeout 300）
        'pool_size': 10,              # 基础连接池大小
        'max_overflow': 20,           # 最大溢出连接数
        'pool_timeout': 30,           # 获取连接超时时间（秒）
        'echo': False,                # 关闭SQL日志
    }
    
    # 设置MySQL连接参数
    app.config['SQLALCHEMY_ENGINE_OPTIONS']['connect_args'] = {
        'connect_timeout': 10,        # 连接超时（秒）
        'read_timeout': 30,          # 读超时（秒）
        'write_timeout': 30,         # 写超时（秒）
        'charset': 'utf8mb4',
        'autocommit': False,
    }

    # 只在非 gunicorn 环境下配置日志
    # gunicorn 会自己管理日志配置
    if not os.environ.get('GUNICORN_WORKER'):
        # 配置结构化日志
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            handlers=[
                logging.StreamHandler(sys.stdout),
                logging.FileHandler('app.log', encoding='utf-8')
            ]
        )

    # 设置各模块日志级别
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)

    # 请求日志中间件
    @app.before_request
    def log_request():
        from flask import request
        # 使用标准 logging 而不是 app.logger
        logging.getLogger('app').info(f"[{request.method}] {request.path} - {request.remote_addr}")

    # 响应日志中间件
    @app.after_request
    def log_response(response):
        from flask import request
        logging.getLogger('app').info(f"[{request.method}] {request.path} - Status: {response.status_code}")
        return response
    
    # CORS 配置（生产环境应限制域名）
    CORS(app, resources={
        r"/api/*": {
            "origins": app.config.get('CORS_ORIGINS', '*'),
            "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"]
        }
    }, supports_credentials=True)

    db.init_app(app)
    JWTManager(app)

    # 注册蓝图
    from routes.auth import auth_bp
    from routes.contacts import contacts_bp
    from routes.groups import groups_bp
    from routes.templates import templates_bp
    from routes.email import email_bp
    from routes.email_senders import email_senders_bp
    from routes.notifications import notifications_bp
    from routes.payment import payment_bp
    from routes.workflow import workflow_bp
    from routes.webhooks import webhooks_bp
    from routes.instance import instance_bp
    from routes.health import health_bp

    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(contacts_bp, url_prefix='/api/contacts')
    app.register_blueprint(groups_bp, url_prefix='/api/groups')
    app.register_blueprint(templates_bp, url_prefix='/api/templates')
    app.register_blueprint(email_bp, url_prefix='/api/email')
    app.register_blueprint(email_senders_bp, url_prefix='/api/email')
    app.register_blueprint(notifications_bp, url_prefix='/api/notifications')
    app.register_blueprint(payment_bp, url_prefix='/api/payment')
    app.register_blueprint(workflow_bp, url_prefix='/api/workflow')
    app.register_blueprint(webhooks_bp, url_prefix='/api/webhooks')
    app.register_blueprint(instance_bp, url_prefix='/api')
    app.register_blueprint(health_bp, url_prefix='/api') # 健康检查

    # 注册错误处理器
    register_error_handlers(app)

    # 初始化调度器（在所有蓝图注册之后）
    from services.scheduler import init_scheduler
    
    with app.app_context():
        # 配置数据库存储并启动
        init_scheduler(app)
        app.logger.info("[Scheduler] Scheduler started successfully")

        # 创建数据库表
        try:
            db.create_all()
            app.logger.info("[Database] Tables created")
        except Exception as e:
            app.logger.error(f"[Database] Error creating tables: {e}")
            # 尝试回滚并重新创建
            try:
                db.session.rollback()
                db.create_all()
                app.logger.info("[Database] Tables created after rollback")
            except Exception as e2:
                app.logger.error(f"[Database] Failed to create tables: {e2}")

    return app


def register_error_handlers(app):
    """注册全局错误处理器"""
    
    # 处理数据库连接错误
    @app.errorhandler(Exception)
    def handle_db_connection_error(error):
        """处理数据库连接错误，尝试清理会话并重试"""
        error_msg = str(error)
        if 'Lost connection to MySQL server' in error_msg or 'MySQL server has gone away' in error_msg:
            # 记录错误但返回友好的响应
            from models import db
            try:
                db.session.rollback()
                db.session.remove()
            except:
                pass
            app.logger.warning(f"[DB] Connection lost, session cleaned up: {error_msg[:100]}")
            return jsonify({
                'success': False,
                'code': 'DB_CONNECTION_LOST',
                'message': 'Database connection lost, please retry'
            }), 503  # Service Unavailable
        
        # 其他未处理的异常
        app.logger.error(f"Unhandled Exception: {str(error)}", exc_info=True)
        return jsonify({
            'success': False,
            'code': 'INTERNAL_ERROR',
            'message': 'An unexpected error occurred'
        }), 500

    @app.errorhandler(400)
    def bad_request(error):
        app.logger.warning(f"Bad Request: {str(error)}")
        return jsonify({
            'success': False,
            'code': 'BAD_REQUEST',
            'message': str(error.description) if hasattr(error, 'description') else 'Bad request'
        }), 400
    
    @app.errorhandler(401)
    def unauthorized(error):
        app.logger.warning(f"Unauthorized: {str(error)}")
        return jsonify({
            'success': False,
            'code': 'UNAUTHORIZED',
            'message': 'Authentication required'
        }), 401
    
    @app.errorhandler(403)
    def forbidden(error):
        app.logger.warning(f"Forbidden: {str(error)}")
        return jsonify({
            'success': False,
            'code': 'FORBIDDEN',
            'message': 'Permission denied'
        }), 403
    
    @app.errorhandler(404)
    def not_found(error):
        app.logger.warning(f"Not Found: {str(error)}")
        return jsonify({
            'success': False,
            'code': 'NOT_FOUND',
            'message': 'Resource not found'
        }), 404
    
    @app.errorhandler(405)
    def method_not_allowed(error):
        app.logger.warning(f"Method Not Allowed: {str(error)}")
        return jsonify({
            'success': False,
            'code': 'METHOD_NOT_ALLOWED',
            'message': 'Method not allowed'
        }), 405
    
    @app.errorhandler(429)
    def too_many_requests(error):
        app.logger.warning(f"Too Many Requests: {str(error)}")
        return jsonify({
            'success': False,
            'code': 'RATE_LIMIT_EXCEEDED',
            'message': 'Too many requests, please try again later'
        }), 429
    
    @app.errorhandler(500)
    def internal_server_error(error):
        app.logger.error(f"Internal Server Error: {str(error)}", exc_info=True)
        return jsonify({
            'success': False,
            'code': 'INTERNAL_ERROR',
            'message': 'An internal error occurred'
        }), 500
    
    @app.errorhandler(Exception)
    def handle_exception(error):
        app.logger.error(f"Unhandled Exception: {str(error)}", exc_info=True)
        return jsonify({
            'success': False,
            'code': 'INTERNAL_ERROR',
            'message': 'An unexpected error occurred'
        }), 500


if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', debug=True, port=8880)

if __name__ == 'app':
    app = create_app()
