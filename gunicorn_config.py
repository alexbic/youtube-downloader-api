"""Gunicorn configuration for unified logging format."""
import logging
from gunicorn.glogging import Logger


class CustomFormatter(logging.Formatter):
    """Custom formatter matching application log format."""

    def format(self, record):
        return f"[{self.formatTime(record, '%Y-%m-%d %H:%M:%S')}] [{record.levelname}] {record.getMessage()}"


class BootingWorkerFilter(logging.Filter):
    """Filter out 'Booting worker with pid' messages."""

    def filter(self, record):
        if "Booting worker with pid" in record.getMessage():
            return False
        return True


class CustomLogger(Logger):
    """Custom logger class that applies formatting from the start."""

    def setup(self, cfg):
        super().setup(cfg)
        formatter = CustomFormatter()
        worker_filter = BootingWorkerFilter()
        for handler in self.error_log.handlers:
            handler.setFormatter(formatter)
            handler.addFilter(worker_filter)
        self.access_log.disabled = True


logger_class = "gunicorn_config.CustomLogger"

accesslog = None
errorlog = "-"
loglevel = "info"


def post_fork(server, worker):
    """Called just after a worker has been forked."""
    import logging
    log = logging.getLogger()
    log.info(f"👷 Worker {worker.pid} ready")
