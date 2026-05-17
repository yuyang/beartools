import logging
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace

import beartools.logger as logger_module


class TestLogger:
    def setup_method(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_cwd = Path.cwd()
        os.chdir(self.temp_dir.name)

    def teardown_method(self) -> None:
        logger_module.shutdown_logging()
        os.chdir(self.original_cwd)
        self.temp_dir.cleanup()

    def test_simple_config_only_uses_queue_handler_and_file_listener(self) -> None:
        log_config = SimpleNamespace(
            path=Path("log/beartools.log"),
            level="INFO",
            config_file=None,
        )

        logger_module._setup_simple_config(log_config)

        root_handlers = list(logging.getLogger().handlers)
        assert len(root_handlers) == 1
        assert root_handlers[0].__class__.__name__ == "QueueHandler"

        queue_listener = logger_module._queue_listener
        assert queue_listener is not None
        listener_handlers = list(queue_listener.handlers)
        assert len(listener_handlers) == 1
        assert listener_handlers[0].__class__.__name__ == "TimedRotatingFileHandler"
        assert all(handler.__class__.__name__ != "StreamHandler" for handler in listener_handlers)
