# type: ignore[misc]
"""Python module to download videos.

This module contains the actual downloaders responsible
for downloading the video files.

"""

from __future__ import annotations

import contextlib
import os
import re
import signal
import subprocess
from pathlib import Path
from queue import Queue
from threading import Thread
from time import sleep
from typing import IO, Any, Callable

from .utils import IS_WINDOWS, get_encoding


# noinspection PyUnresolvedReferences
class PipeReader(Thread):
    """Helper class to avoid deadlocks when reading from subprocess pipes.

    This class uses python threads and queues in order to read from subprocess
    pipes in an asynchronous way.

    Attributes:
        WAIT_TIME (float): Time in seconds to sleep.

    Args:
        queue (Queue): Python queue to store the output of the subprocess.

    Warnings:
        All the operations are based on 'str' types.

    """

    WAIT_TIME = 0.1

    def __init__(self, queue: Queue):
        super().__init__()
        self._filedescriptor: IO[str] | None = None
        self._running: bool = True
        self._queue: Queue[str] = queue
        self.start()

    def run(self) -> None:
        # Flag to ignore specific lines
        ignore_line: bool = False

        while self._running:
            if self._filedescriptor is not None and not self._filedescriptor.closed:
                pipedata: str = self._filedescriptor.read()

                for line in pipedata.splitlines():
                    # Ignore ffmpeg stderr
                    if "ffmpeg version" in line:
                        ignore_line = True
                    if not ignore_line and line:
                        self._queue.put_nowait(line)

                ignore_line = False

            sleep(self.WAIT_TIME)

    def attach_filedescriptor(self, filedesc: IO[str] | None = None) -> None:
        """Attach a filedescriptor to the PipeReader."""
        self._filedescriptor = filedesc

    def join(self, timeout=None) -> None:
        self._running = False
        super().join(timeout)


class YoutubeDLDownloader:
    """Python class for downloading videos using youtube-dl & subprocess.

    Attributes:
        OK, ERROR, STOPPED, ALREADY, FILESIZE_ABORT, WARNING (int): Integers
            that describe the return code from the download() method. The
            larger the number the higher is the hierarchy of the code.
            Codes with smaller hierachy cannot overwrite codes with higher
            hierarchy.

    Args:
        youtubedl_path (str): Absolute path to youtube-dl binary.

        data_hook (Callable): Optional callback function to retrieve download
            process data.

        log_data (Callable): Optional callback function to write data to
            the log file.

    Warnings:
        The caller is responsible for calling the close() method after he has
        finished with the object in order for the object to be able to properly
        close down itself.

    Example:
        How to use YoutubeDLDownloader from a python script.

            from downloaders import YoutubeDLDownloader

            def data_hook(data):
                print(data)

            downloader = YoutubeDLDownloader('/usr/bin/youtube-dl', data_hook)

            downloader.download(<URL STRING>, ['-f', 'flv'])

    """

    OK = 0
    WARNING = 1
    ERROR = 2
    FILESIZE_ABORT = 3
    ALREADY = 4
    STOPPED = 5

    def __init__(
        self,
        youtubedl_path: str,
        data_hook: Callable[[dict[str, Any]], None] | None = None,
        log_data: Callable[[str], None] | None = None,
    ):
        self.youtubedl_path: str = youtubedl_path
        self.data_hook = data_hook
        self.log_data = log_data

        self._return_code: int = self.OK
        self._proc: subprocess.Popen | None = None

        self._stderr_queue: Queue = Queue()
        self._stderr_reader = PipeReader(self._stderr_queue)

    def download(self, url: str, options: list[str] | None = None) -> int:
        """Download url using given options.

        Args:
            url (str): URL string to download.
            options (list): Python list that contains youtube-dl options.

        Returns:
            An integer that shows the status of the download process.
            There are 6 different return codes.

            OK (0): The download process completed successfully.
            WARNING (1): A warning occured during the download process.
            ERROR (2): An error occured during the download process.
            FILESIZE_ABORT (3): The corresponding url video file was larger or
                smaller from the given filesize limit.
            ALREADY (4): The given url is already downloaded.
            STOPPED (5): The download process was stopped by the user.

        """
        self._return_code = self.OK

        cmd = self._get_cmd(url, options)
        self._create_process(cmd)

        if self._proc is not None:
            self._stderr_reader.attach_filedescriptor(self._proc.stderr)

        while self._proc_is_alive():
            stdout: str = ""
            if not self._proc.stdout.closed:
                with contextlib.suppress(ValueError):
                    stdout = self._proc.stdout.readline().rstrip()
            if stdout:
                data_dict = extract_data(stdout)
                self._extract_info(data_dict)
                self._hook_data(data_dict)

        # Read stderr after download process has been completed
        # We don't need to read stderr in real time
        while not self._stderr_queue.empty():
            stderr = str(self._stderr_queue.get_nowait()).rstrip()

            self._log(stderr)

            if self._is_warning(stderr):
                self._set_returncode(self.WARNING)

        if self._proc and self._proc.returncode > 0:
            proc_return_code = self._proc.returncode
            self._log(f"Child process exited with non-zero code: {proc_return_code}")
            self._set_returncode(self.ERROR)

        self._last_data_hook()

        return self._return_code

    def stop(self) -> None:
        """Stop the download process and set return code to STOPPED."""
        if not self._proc_is_alive():
            return

        self._proc.stdout.close()
        self._proc.stderr.close()

        with contextlib.suppress(ProcessLookupError):
            if IS_WINDOWS:
                # os.killpg is not available on Windows
                # See: https://bugs.python.org/issue5115
                self._proc.kill()

                # When we kill the child process on Windows the return code
                # gets set to 1, so we want to reset the return code back to 0
                # in order to avoid creating logging output in the download(...)
                # method
                self._proc.returncode = 0
            else:
                # TODO: Test in Unix os.killpg ?
                os.killpg(self._proc.pid, signal.SIGKILL)  # type: ignore
        self._set_returncode(self.STOPPED)

    def close(self) -> None:
        """Destructor like function for the object."""
        self._stderr_reader.join()

    def _set_returncode(self, code) -> None:
        """Set self._return_code only if the hierarchy of the given code is
        higher than the current self._return_code."""
        if code >= self._return_code:
            self._return_code = code

    @staticmethod
    def _is_warning(stderr: str) -> bool:
        warning_error = stderr.split(":")[0]
        warning_error = warning_error.strip()
        return warning_error in ["WARNING", "ERROR"]

    def _last_data_hook(self) -> None:
        """Set the last data information based on the return code."""
        data_dictionary: dict[str, str] = {
            "status": "",
            "speed": "",
            "eta": "",
        }

        if self._return_code == self.OK:
            data_dictionary["status"] = "Finished"
        elif self._return_code == self.ERROR:
            data_dictionary["status"] = "Error"
        elif self._return_code == self.WARNING:
            data_dictionary["status"] = "Warning"
        elif self._return_code == self.STOPPED:
            data_dictionary["status"] = "Stopped"
        elif self._return_code == self.ALREADY:
            data_dictionary["status"] = "Already Downloaded"
        else:
            data_dictionary["status"] = "Filesize Abort"

        self._hook_data(data_dictionary)

    def _extract_info(self, data: dict[str, Any]) -> None:
        """Extract informations about the download process from the given data.

        Args:
            data (dict): Python dictionary that contains different
                keys. The keys are not standar the dictionary can also be
                empty when there are no data to extract. See extract_data().

        """
        if "status" in data:
            if data["status"] == "Already Downloaded":
                # Set self._return_code to already downloaded
                # and trash that key
                self._set_returncode(self.ALREADY)
                data["status"] = None

            if data["status"] == "Filesize Abort":
                # Set self._return_code to filesize abort
                # and trash that key
                self._set_returncode(self.FILESIZE_ABORT)
                data["status"] = None

    def _log(self, data: str) -> None:
        """Log data using the callback function."""
        if self.log_data is not None:
            self.log_data(data)

    def _hook_data(self, data: dict[str, Any]):
        """Pass data back to the caller."""
        if self.data_hook is not None:
            self.data_hook(data)

    def _proc_is_alive(self) -> bool:
        """Returns True if self._proc is alive else False."""
        return False if self._proc is None else self._proc.poll() is None

    def _get_cmd(self, url: str, options: list[str] | None = None) -> list[str]:
        """Build the subprocess command.

        Args:
            url (str): URL string to download.
            options (list): Python list that contains youtube-dl options.

        Returns:
            Python list that contains the command to execute.

        """
        cmd_list: list[str] = [self.youtubedl_path]

        if options:
            cmd_list.extend(options)

        cmd_list.append(url)
        return cmd_list

    def _create_process(self, cmd: list[str]) -> None:
        """Create new subprocess.

        Args:
            cmd (list): Python list that contains the command to execute.

        """
        info = None

        kwargs = dict(
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            encoding=get_encoding(),
            creationflags=0,
        )

        if os.name == "nt":
            # Hide subprocess window
            info = subprocess.STARTUPINFO()
            info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            info.wShowWindow = subprocess.SW_HIDE

            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True

        try:
            self._proc = subprocess.Popen(cmd, startupinfo=info, **kwargs)  # type: ignore
        except (ValueError, OSError) as error:
            self._log(f"Failed to start process: {cmd}")
            self._log(str(error))


def extract_filename(input_data: str) -> tuple[str, str, str]:
    """Extract the component of the filename

    Args:
        input_data (str): Filename with extension

    Returns:
        Python tuple with path, filename and extension

    """
    _filename = Path(input_data.strip('"'))
    path: str = str(_filename.parent) if str(_filename.parent) != "." else ""
    filename: str = _filename.stem
    extension: str = _filename.suffix

    return path, filename, extension


def extract_data(stdout: str) -> dict[str, str]:
    """Extract data from youtube-dl stdout.

    Args:
        stdout (str): String that contains the youtube-dl stdout.

    Returns:
        Python dictionary. The returned dictionary can be empty if there are
        no data to extract else it may contain one or more of the
        following keys:

        'status'         : Contains the status of the download process.
        'path'           : Destination path.
        'extension'      : The file extension.
        'filename'       : The filename without the extension.
        'percent'        : The percentage of the video being downloaded.
        'eta'            : Estimated time for the completion of the download process.
        'speed'          : Download speed.
        'filesize'       : The size of the video file being downloaded.
        'playlist_index' : The playlist index of the current video file being downloaded.
        'playlist_size'  : The number of videos in the playlist.

    """
    # REFACTOR
    # noinspection PyShadowingNames

    data_dictionary: dict[str, str] = {}

    if not stdout:
        return data_dictionary

    # We want to keep the spaces in order to extract filenames with
    # multiple whitespaces correctly.
    # Fix output of yt-dlp compatible with youtube-dl
    stdout_list: list[str] = re.sub(r"~\s+", "~", stdout, count=1).split()

    stdout_list[0] = stdout_list[0].lstrip("\r")

    if stdout_list[0] == "[download]":
        data_dictionary["status"] = "Downloading"

        # Get path, filename & extension
        if stdout_list[1] == "Destination:":
            path, filename, extension = extract_filename(" ".join(stdout_list[2:]))

            data_dictionary["path"] = path
            data_dictionary["filename"] = filename
            data_dictionary["extension"] = extension

        # Get progress info
        if "%" in stdout_list[1]:
            if stdout_list[1] == "100%":
                data_dictionary["speed"] = ""
                data_dictionary["eta"] = ""
                data_dictionary["percent"] = "100%"
                data_dictionary["filesize"] = stdout_list[3]
            else:
                data_dictionary["percent"] = stdout_list[1]
                data_dictionary["filesize"] = stdout_list[3]
                data_dictionary["speed"] = stdout_list[5]
                data_dictionary["eta"] = stdout_list[7]

        # Get playlist info
        if stdout_list[1] == "Downloading" and stdout_list[2] == "video":
            data_dictionary["playlist_index"] = stdout_list[3]
            data_dictionary["playlist_size"] = stdout_list[5]

        # Remove the 'and merged' part from stdout when using ffmpeg to merge the formats
        if stdout_list[-3] == "downloaded" and stdout_list[-1] == "merged":
            stdout_list = stdout_list[:-2]
            data_dictionary["percent"] = "100%"

        # Get file already downloaded status
        if stdout_list[-1] == "downloaded":
            data_dictionary["status"] = "Already Downloaded"
            path, filename, extension = extract_filename(" ".join(stdout_list[1:-4]))

            data_dictionary["path"] = path
            data_dictionary["filename"] = filename
            data_dictionary["extension"] = extension

        # Get filesize abort status
        if stdout_list[-1] == "Aborting.":
            data_dictionary["status"] = "Filesize Abort"

    elif stdout_list[0] == "[hlsnative]":
        # native hls extractor
        # see: https://github.com/rg3/youtube-dl/blob/master/youtube_dl/downloader/hls.py#L54
        data_dictionary["status"] = "Downloading"

        if len(stdout_list) == 7:
            segment_no = float(stdout_list[6])
            current_segment = float(stdout_list[4])

            # Get the percentage
            percent = f"{current_segment / segment_no * 100:.1f}%"
            data_dictionary["percent"] = percent

    elif stdout_list[0] == "[ffmpeg]":
        data_dictionary["status"] = "Post Processing"

        # Get final extension after merging process
        if stdout_list[1] == "Merging":
            path, filename, extension = extract_filename(" ".join(stdout_list[4:]))

            data_dictionary["path"] = path
            data_dictionary["filename"] = filename
            data_dictionary["extension"] = extension

        # Get final extension ffmpeg post process simple (not file merge)
        if stdout_list[1] == "Destination:":
            path, filename, extension = extract_filename(" ".join(stdout_list[2:]))

            data_dictionary["path"] = path
            data_dictionary["filename"] = filename
            data_dictionary["extension"] = extension

        # Get final extension after recoding process
        if stdout_list[1] == "Converting":
            path, filename, extension = extract_filename(" ".join(stdout_list[8:]))

            data_dictionary["path"] = path
            data_dictionary["filename"] = filename
            data_dictionary["extension"] = extension

    elif stdout_list[0][0] == "[" and stdout_list[0] != "[debug]":
        data_dictionary["status"] = "Pre Processing"

    return data_dictionary
