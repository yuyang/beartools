import importlib
import os
from pathlib import Path
import tempfile
from typing import Protocol, cast

pytest = importlib.import_module("pytest")
logging = importlib.import_module("logging")
logger_module = importlib.import_module("beartools.logger")


class _LogModule(Protocol):
    def _setup_simple_config(self, log_config: object) -> None: ...

    def shutdown_logging(self) -> None: ...


class _LogConfig(Protocol):
    path: Path
    level: str
    config_file: object


_LOGGER_MODULE = logger_module


class TestLogger:
    def setup_method(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_cwd = Path.cwd()
        os.chdir(self.temp_dir.name)

    def teardown_method(self) -> None:
        _LOGGER_MODULE.shutdown_logging()
        os.chdir(self.original_cwd)
        self.temp_dir.cleanup()

    def test_simple_config_only_uses_queue_handler_and_file_listener(self) -> None:
        log_config = cast(
            _LogConfig,
            type(
                "LogConfig",
                (),
                {
                    "path": Path("log/beartools.log"),
                    "level": "INFO",
                    "config_file": None,
                },
            )(),
        )

        _LOGGER_MODULE._setup_simple_config(log_config)

        root_handlers = list(logging.getLogger().handlers)
        assert len(root_handlers) == 1
        assert root_handlers[0].__class__.__name__ == "QueueHandler"

        queue_listener = cast(object, _LOGGER_MODULE._queue_listener)
        listener_handlers = list(queue_listener.handlers)
        assert len(listener_handlers) == 1
        assert listener_handlers[0].__class__.__name__ == "TimedRotatingFileHandler"
        assert all(handler.__class__.__name__ != "StreamHandler" for handler in listener_handlers)
