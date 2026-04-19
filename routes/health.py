"""
健康检查路由 - 提供系统状态监控接口
"""
from flask import Blueprint, jsonify, current_app
from models import db
from sqlalchemy import text
import os
import psutil
from datetime import datetime

health_bp = Blueprint('health', __name__)

# 应用启动时间
_app_start_time = datetime.utcnow()


@health_bp.route('/health', methods=['GET'])
def health_check():
    """
    基础健康检查
    返回: 200 OK 如果应用正常运行
    """
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'uptime': str(datetime.utcnow() - _app_start_time)
    }), 200


@health_bp.route('/health/ready', methods=['GET'])
def readiness_check():
    """
    就绪检查 - 验证数据库连接
    用于 Kubernetes readiness probe
    """
    try:
        # 测试数据库连接
        db.session.execute(text('SELECT 1'))
        return jsonify({
            'status': 'ready',
            'database': 'connected',
            'timestamp': datetime.utcnow().isoformat()
        }), 200
    except Exception as e:
        current_app.logger.error(f"Readiness check failed: {str(e)}")
        return jsonify({
            'status': 'not_ready',
            'database': 'disconnected',
            'error': str(e)
        }), 503


@health_bp.route('/health/live', methods=['GET'])
def liveness_check():
    """
    存活检查 - 验证应用是否运行
    用于 Kubernetes liveness probe
    """
    return jsonify({
        'status': 'alive',
        'timestamp': datetime.utcnow().isoformat()
    }), 200


@health_bp.route('/health/metrics', methods=['GET'])
def metrics_check():
    """
    系统指标检查 - 返回详细的系统状态
    包含数据库、内存、CPU、磁盘等信息
    """
    metrics = {
        'timestamp': datetime.utcnow().isoformat(),
        'uptime': str(datetime.utcnow() - _app_start_time),
    }
    
    # 数据库状态
    try:
        db.session.execute(text('SELECT 1'))
        metrics['database'] = {
            'status': 'connected',
            'latency_ms': 0  # 可以添加查询耗时测量
        }
    except Exception as e:
        metrics['database'] = {
            'status': 'disconnected',
            'error': str(e)
        }
    
    # 系统资源
    try:
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        cpu_percent = psutil.cpu_percent(interval=0.1)
        
        metrics['system'] = {
            'memory': {
                'total_mb': memory.total // (1024 * 1024),
                'available_mb': memory.available // (1024 * 1024),
                'percent_used': memory.percent
            },
            'disk': {
                'total_gb': disk.total // (1024 * 1024 * 1024),
                'free_gb': disk.free // (1024 * 1024 * 1024),
                'percent_used': (disk.used / disk.total) * 100
            },
            'cpu': {
                'percent_used': cpu_percent
            }
        }
    except Exception as e:
        metrics['system'] = {
            'error': f'Failed to get system metrics: {str(e)}'
        }
    
    # 应用配置（脱敏）
    metrics['config'] = {
        'mock_email': current_app.config.get('MOCK_EMAIL_SEND', True),
        'aws_region': current_app.config.get('AWS_REGION', 'not_set'),
        'database_type': 'mysql' if 'mysql' in str(current_app.config.get('SQLALCHEMY_DATABASE_URI', '')) else 'other'
    }
    
    return jsonify(metrics), 200


@health_bp.route('/health/version', methods=['GET'])
def version_info():
    """
    版本信息
    """
    return jsonify({
        'version': os.environ.get('APP_VERSION', '1.0.0'),
        'environment': os.environ.get('FLASK_ENV', 'production'),
        'build_time': os.environ.get('BUILD_TIME', 'unknown')
    }), 200
