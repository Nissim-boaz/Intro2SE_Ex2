# Gunicorn configuration
import multiprocessing

bind = "0.0.0.0:5050"
workers = 4
threads = 2
worker_class = "gthread"
timeout = 30
keepalive = 5
accesslog = "-"
errorlog = "-"
loglevel = "info"
