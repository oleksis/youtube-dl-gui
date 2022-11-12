"""yt-dlg module responsible for handling the log stuff. """


import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .utils import check_path, get_encoding  # type: ignore[attr-defined]


class LogManager:
    """Simple log manager for youtube-dl.

    This class is mainly used to log the youtube-dl STDERR.

    Attributes:
        LOG_FILENAME (str): Filename of the log file.
        MAX_LOGSIZE (int): Maximum size(Bytes) of the log file.

    Args:
        config_path (str): Absolute path where LogManager should
            store the log file.

        add_time (bool): If True LogManager will also log the time.

    """

    LOG_FILENAME = "log"
    MAX_LOGSIZE = 524288  # Bytes

    def __init__(self, config_path: str, add_time: bool = False):
        self.config_path: str = config_path
        self.add_time: bool = add_time
        self.log_file: str = str(Path(config_path) / Path(self.LOG_FILENAME))
        self._encoding: str = get_encoding()
        self.logger: logging.Logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)

        check_path(self.config_path)

        self.handler = RotatingFileHandler(
            filename=self.log_file,
            maxBytes=LogManager.MAX_LOGSIZE,
            backupCount=5,
            encoding=self._encoding,
        )

        fmt = "%(levelname)s-%(threadName)s-%(message)s"

        if self.add_time:
            fmt = f"%(asctime)s-{fmt}"

        self.handler.setFormatter(logging.Formatter(fmt=fmt))
        self.logger.addHandler(self.handler)

    def log_size(self) -> int:
        """Return log file size in Bytes."""
        path = Path(self.log_file)

        return path.stat().st_size if path.exists() else 0

    def clear(self) -> None:
        """Clear log file."""
        with open(self.log_file, "w") as log:
            log.write("")

    def log(self, data: str) -> None:
        """Log data to the log file.

        Args:
            data (str): String to write to the log file.

        """
        self.logger.debug(data)
