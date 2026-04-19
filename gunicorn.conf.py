import multiprocessing

# 服务器绑定
bind = "0.0.0.0:8880"
backlog = 2048

# 工作进程
workers = multiprocessing.cpu_count() * 2
worker_class = "gevent"
worker_connections = 1000
timeout = 30
keepalive = 5
threads = 4

daemon = True
debug = True

# 服务进程 
pidfile = "/data/wwwroot/mail/pyback/log/back.pid"
# 访问日志路径
accesslog = "/data/wwwroot/mail/pyback/log/back_access.log"
# 错误信息日志路径
errorlog = "/data/wwwroot/mail/pyback/log/back_error.log"
# 设置日志记录水平
loglevel = "info"

# 性能优化
max_requests = 1000
max_requests_jitter = 100
preload_app = True
