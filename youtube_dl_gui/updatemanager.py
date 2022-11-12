# type: ignore[misc]
"""yt-dlg module to update youtube-dl binary.

Attributes:
    UPDATE_PUB_TOPIC (str): wxPublisher subscription topic of the
        UpdateThread thread.

"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from threading import Thread
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import wx

# noinspection PyPep8Naming
from pubsub import pub as Publisher

from .utils import IS_WINDOWS, YOUTUBEDL_BIN, YTDLP_BIN, check_path

UPDATE_PUB_TOPIC = "update"

if TYPE_CHECKING:
    from .optionsmanager import OptionsManager


class UpdateThread(Thread):
    """Python Thread that downloads youtube-dl binary.

    Attributes:
        LATEST_YOUTUBE_DL (str): URL with the latest youtube-dl binary.

        GITHUB_API (str): URL GitHub API v3

        LATEST_YOUTUBE_DL_API (str): See `LATEST_YOUTUBE_DL` attribute

        DOWNLOAD_TIMEOUT (int): Download timeout in seconds.

    Args:
        opt_manager (optionsmanager.OptionsManager): Options manager

        quiet (bool): If True UpdateThread won't send the finish signal
            back to the caller. Finish signal can be used to make sure that
            the UpdateThread has been completed in an asynchronous way.

        daemon (bool): If Thread is daemonic

    """

    LATEST_YOUTUBE_DL: str = "https://yt-dl.org/latest/"
    GITHUB_API: str = "https://api.github.com/"
    LATEST_YOUTUBE_DL_API: str = (
        GITHUB_API + "repos/ytdl-org/youtube-dl/releases/latest"
    )
    DOWNLOAD_TIMEOUT: int = 10

    def __init__(
        self,
        opt_manager: OptionsManager,
        quiet: bool = False,
        daemon: bool = False,
    ):
        super().__init__()
        self.opt_manager = opt_manager
        self.download_path: str = opt_manager.options.get("youtubedl_path", ".")
        self.cli_backend: str = opt_manager.options.get("cli_backend", YOUTUBEDL_BIN)
        self.quiet: bool = quiet

        if self.cli_backend == YTDLP_BIN:
            self.LATEST_YOUTUBE_DL = "https://github.com/yt-dlp/yt-dlp/releases/"
            self.LATEST_YOUTUBE_DL_API = (
                f"{self.GITHUB_API}repos/yt-dlp/yt-dlp/releases/latest"
            )

        self.name = "UpdateManager"
        self.daemon = daemon
        self.start()

    def get_latest_sourcefile(self) -> str:
        """Get the URL file name of the latest asset"""
        source_file: str = self.GITHUB_API
        try:
            stream = urlopen(self.LATEST_YOUTUBE_DL_API, timeout=self.DOWNLOAD_TIMEOUT)

            latest_json: dict[str, Any] = json.load(stream)
            latest_assets: list[dict[str, Any]] = latest_json["assets"]

            for asset in latest_assets:
                if asset["name"] == self.cli_backend:
                    source_file = asset["browser_download_url"]
                    break
        except (HTTPError, URLError, json.JSONDecodeError) as error:
            self._talk_to_gui("error", str(error))

        return source_file

    def run(self) -> None:
        self._talk_to_gui("download")

        source_file: str = self.get_latest_sourcefile()
        destination_file: str = str(Path(self.download_path) / Path(self.cli_backend))

        check_path(self.download_path)

        try:
            stream = urlopen(source_file, timeout=self.DOWNLOAD_TIMEOUT)

            with open(destination_file, "wb") as dest_file:
                dest_file.write(stream.read())

            # Have to set the executable flag on linux
            if not IS_WINDOWS:
                mode = os.stat(destination_file).st_mode
                mode |= mode | stat.S_IEXEC
                os.chmod(destination_file, mode)

            self._talk_to_gui("correct")
        except (HTTPError, URLError, OSError) as error:
            self._talk_to_gui("error", str(error))

        if not self.quiet:
            self._talk_to_gui("finish")

    @staticmethod
    def _talk_to_gui(signal: str, data: str | None = None) -> None:
        """Communicate with the GUI using wxCallAfter and wxPublisher.

        Args:
            signal (str): Unique signal string that informs the GUI for the
                update process.

            data (str): Can be any string data to pass along with the
                given signal. Default is None.

        Note:
            UpdateThread supports 4 signals.
                1) download: The update process started
                2) correct: The update process completed successfully
                3) error: An error occured while downloading youtube-dl binary
                4) finish: The update thread is ready to join

        """
        if wx.GetApp() is not None:
            wx.CallAfter(
                Publisher.sendMessage, UPDATE_PUB_TOPIC, signal=signal, data=data
            )
