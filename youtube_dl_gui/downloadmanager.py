# type: ignore[misc]
"""yt-dlg module for managing the download process.

This module is responsible for managing the download process
and update the GUI interface.

Attributes:
    MANAGER_PUB_TOPIC (str): Publisher subscription topic of the
        DownloadManager thread.

    WORKER_PUB_TOPIC (str): Publisher subscription topic of the
        Worker thread.

Note:
    It's not the actual module that downloads the urls
    thats the job of the 'downloaders' module.

"""
from __future__ import annotations

import time
from pathlib import Path
from threading import RLock, Thread
from typing import TYPE_CHECKING, Any, Callable

import wx

# noinspection PyPep8Naming
from pubsub import pub as Publisher

from .downloaders import YoutubeDLDownloader
from .parsers import OptionsParser
from .updatemanager import UpdateThread
from .utils import YOUTUBEDL_BIN, format_bytes, to_bytes

if TYPE_CHECKING:
    from .logmanager import LogManager
    from .mainframe import MainFrame
    from .optionsmanager import OptionsManager

MANAGER_PUB_TOPIC = "dlmanager"
WORKER_PUB_TOPIC = "dlworker"

_SYNC_LOCK = RLock()


def synchronized(lock: RLock) -> Callable[..., Any]:
    """Decorator that adds thread synchronization to a function"""

    def _decorator(func: Callable) -> Callable[..., Any]:
        def _wrapper(*args, **kwargs) -> Any:
            lock.acquire()
            ret_value: Any = func(*args, **kwargs)
            lock.release()
            return ret_value

        return _wrapper

    return _decorator


class DownloadItem:
    """Object that represents a download.

    Attributes:
        STAGES (tuple): Main stages of the download item.

        ACTIVE_STAGES (tuple): Sub stages of the 'Active' stage.

        COMPLETED_STAGES (tuple): Sub stages of the 'Completed' stage.

        ERROR_STAGES (tuple): Sub stages of the 'Error' stage.

    Args:
        url (string): URL that corresponds to the download item.

        options (list): Options list to use during the download phase.

    """

    STAGES = ("Queued", "Active", "Paused", "Completed", "Error")

    ACTIVE_STAGES = ("Pre Processing", "Downloading", "Post Processing")

    COMPLETED_STAGES = ("Finished", "Warning", "Already Downloaded")

    ERROR_STAGES = ("Error", "Stopped", "Filesize Abort")

    def __init__(self, url: str, options: list[str]):
        self.url: str = url
        self.options: list[str] = options
        self.object_id: int = hash(url + str(options))
        self._stage: str = self.STAGES[0]
        self.path: str = ""
        self.filenames: list[str] = []
        self.extensions: list[str] = []
        self.filesizes: list[float] = []
        self.progress_stats: dict[str, str] = {}
        self.playlist_index_changed: bool = False

        self.reset()

    @property
    def stage(self) -> str:
        return self._stage

    @stage.setter
    def stage(self, value: str) -> None:
        if value not in self.STAGES:
            raise ValueError(value)

        if value == "Active":
            self.progress_stats["status"] = self.ACTIVE_STAGES[0]
        elif value == "Completed":
            self.progress_stats["status"] = self.COMPLETED_STAGES[0]
        elif value == "Error":
            self.progress_stats["status"] = self.ERROR_STAGES[0]

        elif value in {"Queued", "Paused"}:
            self.progress_stats["status"] = value
        self._stage = value

    def _init_filename_sizes_extensions(self) -> None:
        self.filenames = []
        self.extensions = []
        self.filesizes = []

    def reset(self) -> None:
        if self._stage == self.STAGES[1]:
            raise RuntimeError("Cannot reset an 'Active' item")

        self._stage = self.STAGES[0]
        self.path = ""
        self._init_filename_sizes_extensions()

        self.default_values: dict[str, str] = {
            "filename": self.url,
            "extension": "-",
            "filesize": "-",
            "percent": "0%",
            "speed": "-",
            "eta": "-",
            "status": self.stage,
            "playlist_size": "",
            "playlist_index": "",
        }

        self.progress_stats = dict(self.default_values)
        # Keep track when the 'playlist_index' changes
        self.playlist_index_changed = False

    def get_files(self) -> list[str]:
        """Returns a list that contains all the system files bind to this object."""
        return [
            str(Path(self.path) / Path(item + self.extensions[index]))
            for index, item in enumerate(self.filenames)
        ]

    def update_stats(self, stats_dict: dict[str, Any]) -> None:
        """Updates the progress_stats dict from the given dictionary."""
        assert isinstance(stats_dict, dict)

        for key in stats_dict:
            if key in self.progress_stats:
                value = stats_dict.get(key)

                self.progress_stats[key] = value or self.default_values[key]
        # Extract extra stuff
        if "playlist_index" in stats_dict:
            self.playlist_index_changed = True

        if "filename" in stats_dict:
            # Reset filenames, extensions & filesizes lists when changing playlist item
            if self.playlist_index_changed:
                self._init_filename_sizes_extensions()
                self.playlist_index_changed = False

            self.filenames.append(stats_dict["filename"])

        if "extension" in stats_dict:
            self.extensions.append(stats_dict["extension"])

        if "path" in stats_dict:
            self.path = stats_dict["path"]

        if (
            "filesize" in stats_dict
            and stats_dict["percent"] == "100%"
            and len(self.filesizes) < len(self.filenames)
        ):
            filesize = stats_dict["filesize"].lstrip("~")  # HLS downloader etc
            self.filesizes.append(to_bytes(filesize))

        if "status" in stats_dict:
            # If we are post processing try to calculate the size of
            # the output file since youtube-dl does not
            if (
                stats_dict["status"] == self.ACTIVE_STAGES[2]
                and len(self.filesizes) == 2
            ):
                post_proc_filesize = self.filesizes[0] + self.filesizes[1]

                self.filesizes.append(post_proc_filesize)
                self.progress_stats["filesize"] = format_bytes(post_proc_filesize)

            self._set_stage(stats_dict["status"])

    def _set_stage(self, status: str) -> None:
        if status in self.ACTIVE_STAGES:
            self._stage = self.STAGES[1]

        if status in self.COMPLETED_STAGES:
            self._stage = self.STAGES[3]

        if status in self.ERROR_STAGES:
            self._stage = self.STAGES[4]

    def __eq__(self, other: object) -> bool:
        return (
            self.object_id == other.object_id
            if isinstance(other, DownloadItem)
            else NotImplemented
        )

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}({self.url},{self.options})>"


class DownloadList:
    """List like data structure that contains DownloadItems.

    Args:
        items (list): List that contains DownloadItems.

    """

    def __init__(self, items: list[DownloadItem] | None = None):
        assert isinstance(items, list) or items is None

        self._items_dict: dict[int, DownloadItem] = {}  # Speed up lookup
        self._items_list: list[int] = []  # Keep the sequence

        if items:
            self._items_list = [item.object_id for item in items]
            self._items_dict = {item.object_id: item for item in items}

    @synchronized(_SYNC_LOCK)
    def clear(self) -> None:
        """Removes all the items from the list even the 'Active' ones."""
        self._items_list = []
        self._items_dict = {}

    @synchronized(_SYNC_LOCK)
    def insert(self, item: DownloadItem) -> None:
        """Inserts the given item to the list. Does not check for duplicates."""
        self._items_list.append(item.object_id)
        self._items_dict[item.object_id] = item

    @synchronized(_SYNC_LOCK)
    def remove(self, object_id: int | None) -> bool:
        """Removes an item from the list.

        Removes the item with the corresponding object_id from
        the list if the item is not in 'Active' state.

        Returns:
            True on success else False.

        """
        assert object_id is not None

        item = self._items_dict[object_id]

        if item and item.stage != "Active":
            self._items_list.remove(object_id)
            del self._items_dict[object_id]

            return True
        return False

    @synchronized(_SYNC_LOCK)
    def fetch_next(self) -> DownloadItem | None:
        """Returns the next queued item on the list.

        Returns:
            Next queued item or None if no other item exist.

        """
        for object_id in self._items_list:
            cur_item = self._items_dict[object_id]
            if cur_item.stage == "Queued":
                return cur_item

        return None

    @synchronized(_SYNC_LOCK)
    def move_up(self, object_id: int):
        """Moves the item with the corresponding object_id up to the list."""
        index: int = self._items_list.index(object_id)

        if index > 0:
            self._swap(index, index - 1)
            return True

        return False

    @synchronized(_SYNC_LOCK)
    def move_down(self, object_id: int):
        """Moves the item with the corresponding object_id down to the list."""
        index: int = self._items_list.index(object_id)

        if index < (len(self._items_list) - 1):
            self._swap(index, index + 1)
            return True

        return False

    @synchronized(_SYNC_LOCK)
    def get_item(self, object_id: int | None) -> DownloadItem | None:
        """Returns the DownloadItem with the given object_id."""
        assert object_id is not None
        return self._items_dict.get(object_id, None)

    @synchronized(_SYNC_LOCK)
    def has_item(self, object_id: int) -> bool:
        """Returns True if the given object_id is in the list else False."""
        return object_id in self._items_list

    @synchronized(_SYNC_LOCK)
    def get_items(self) -> list[DownloadItem]:
        """Returns a list with all the items."""
        return [self._items_dict[object_id] for object_id in self._items_list]

    @synchronized(_SYNC_LOCK)
    def change_stage(self, object_id: int, new_stage: str) -> None:
        """Change the stage of the item with the given object_id."""
        self._items_dict[object_id].stage = new_stage

    @synchronized(_SYNC_LOCK)
    def index(self, object_id: int) -> int:
        """Get the zero based index of the item with the given object_id."""
        if object_id in self._items_list:
            return self._items_list.index(object_id)
        return -1

    @synchronized(_SYNC_LOCK)
    def __len__(self) -> int:
        return len(self._items_list)

    @synchronized(_SYNC_LOCK)
    def __repr__(self) -> str:
        return str(dict(self._items_dict.items()))

    def _swap(self, index1: int, index2: int) -> None:
        self._items_list[index1], self._items_list[index2] = (
            self._items_list[index2],
            self._items_list[index1],
        )


class DownloadManager(Thread):
    """Manages the download process.

    Attributes:
        WAIT_TIME (float): Time in seconds to sleep.

    Args:
        parent (mainframe.MainFrame): Main Frame

        download_list (DownloadList): List that contains items to download.

        opt_manager (optionsmanager.OptionsManager): Object responsible for
            managing the yt-dlg options.

        log_manager (logmanager.LogManager): Object responsible for writing
            errors to the log.

        daemon (bool): If Thread is daemonic

    """

    WAIT_TIME = 0.1

    def __init__(
        self,
        parent: MainFrame,
        download_list: DownloadList,
        opt_manager: OptionsManager,
        log_manager: LogManager | None = None,
        daemon=False,
    ):
        super().__init__()
        self.parent = parent
        self.opt_manager = opt_manager
        self.log_manager = log_manager
        self.download_list = download_list

        self._time_it_took: float = 0
        self._successful = 0
        self._running = True

        # Init the custom workers thread pool
        self._workers = [
            Worker(opt_manager, self._youtubedl_path(), log_manager, worker=worker)
            for worker in range(1, int(opt_manager.options["workers_number"]) + 1)
        ]

        self.name = "DownloadManager"
        self.daemon = daemon
        self.start()

    @property
    def successful(self) -> int:
        """Returns number of successful downloads."""
        return self._successful

    @property
    def time_it_took(self) -> float:
        """Returns time(seconds) it took for the download process
        to complete."""
        return self._time_it_took

    def run(self) -> None:
        if not self.opt_manager.options["disable_update"]:
            self._check_youtubedl()

        self._time_it_took = time.time()

        # TODO: Use threading.Condition
        while self._running:
            item: DownloadItem | None = self.download_list.fetch_next()

            if item is not None:
                worker = self._get_worker()

                if worker is not None:
                    worker.download(item.url, item.options, item.object_id)
                    self.download_list.change_stage(item.object_id, "Active")

            if item is None and self._jobs_done():
                break

            time.sleep(self.WAIT_TIME)

        # Close all the workers and collect
        for worker in self._workers:
            worker.close()
            self._successful += worker.successful

        self._time_it_took = time.time() - self._time_it_took

        if not self._running:
            self._talk_to_gui("closed")
        else:
            self._talk_to_gui("finished")

    def active(self) -> int:
        """Returns number of active items."""
        return len(self.download_list)

    def stop_downloads(self) -> None:
        """Stop the download process. Also send 'closing'
        signal back to the GUI.

        Note:
            It does NOT kill the workers thats the job of the
            clean up task in the run() method.

        """
        self._talk_to_gui("closing")
        self._running = False

    def send_to_worker(self, data: dict[str, Any]) -> None:
        """Send data to the Workers.

        Args:
            data (dict): Python dictionary that holds the 'index'
            which is used to identify the Worker thread and the data which
            can be any of the Worker's class valid data. For a list of valid
            data keys see __init__() under the Worker class.

        """
        if "index" in data:
            for worker in self._workers:
                if worker.has_index(data["index"]):
                    worker.update_data(data)

    @staticmethod
    def _talk_to_gui(signal: str, data: dict[str, Any] | None = None) -> None:
        """Send data back to the GUI using wxCallAfter and wxPublisher.

        Args:
            signal (string): Unique signal string that informs the GUI for the
                download process.

        Note:
            DownloadManager supports 4 signals.
                1) closing: The download process is closing.
                2) closed: The download process has closed.
                3) finished: The download process was completed normally.
                4) report_active: Signal the gui to read the number of active
                    downloads using the active() method.

        """
        if wx.GetApp() is not None:
            wx.CallAfter(
                Publisher.sendMessage, MANAGER_PUB_TOPIC, signal=signal, data=data
            )

    def _check_youtubedl(self) -> None:
        """Check if youtube-dl binary exists. If not try to download it."""
        ytdl_path = self._youtubedl_path()
        if not Path(ytdl_path).exists() and self.parent.update_thread is None:
            self.parent.update_thread = UpdateThread(self.opt_manager, True)
            self.parent.update_thread.join()
            self.parent.update_thread = None

    def _get_worker(self) -> Worker | None:
        return next((worker for worker in self._workers if worker.available()), None)

    def _jobs_done(self) -> bool:
        """Returns True if the workers have finished their jobs else False."""
        return all(worker.available() for worker in self._workers)

    def _youtubedl_path(self) -> str:
        """Returns the path to youtube-dl binary."""
        cli_backend: str = self.opt_manager.options.get("cli_backend", YOUTUBEDL_BIN)
        return str(Path(self.opt_manager.options["youtubedl_path"]) / Path(cli_backend))

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}({self.download_list})>"


class Worker(Thread):
    """Simple worker which downloads the given url using a downloader
    from the downloaders.py module.

    Attributes:
        WAIT_TIME (float): Time in seconds to sleep.

        worker_count (int): Numer of worker threads

    Args:
        opt_manager (optionsmanager.OptionsManager): Check DownloadManager
            description.

        youtubedl_path (str): Absolute path to youtube-dl binary.

        log_manager (logmanager.LogManager): Check DownloadManager
            description.

        worker (int): Worker thread number

    Note:
        For available data keys see self._data under the __init__() method.

    """

    WAIT_TIME = 0.1
    worker_count = 0

    def __init__(
        self,
        opt_manager: OptionsManager,
        youtubedl_path: str,
        log_manager: LogManager | None = None,
        worker: int | None = None,
    ):
        super().__init__()
        # Use Daemon ?
        # self.setDaemon(True)
        Worker.worker_count += 1
        self.opt_manager = opt_manager
        self.log_manager = log_manager
        self.worker = worker or Worker.worker_count
        self.setName(f"Worker_{worker}")

        self._downloader = YoutubeDLDownloader(
            youtubedl_path, self._data_hook, self._log_data
        )
        self._options_parser = OptionsParser()
        self._successful = 0
        self._running = True
        self._options: list[str] | None = None

        self._wait_for_reply = False

        self._data: dict[str, Any] = {
            "playlist_index": None,
            "playlist_size": None,
            "new_filename": None,
            "extension": None,
            "filesize": None,
            "filename": None,
            "percent": None,
            "status": None,
            "index": None,
            "speed": None,
            "path": None,
            "eta": None,
            "url": None,
        }

        self.start()

    def run(self) -> None:
        # TODO: Use threading.Condition
        while self._running:
            if self._data.get("url"):
                ret_code = self._downloader.download(self._data["url"], self._options)

                if ret_code in [
                    YoutubeDLDownloader.OK,
                    YoutubeDLDownloader.ALREADY,
                    YoutubeDLDownloader.WARNING,
                ]:
                    self._successful += 1

                self._reset()

            time.sleep(self.WAIT_TIME)

        # Call the destructor function of YoutubeDLDownloader object
        self._downloader.close()

    # noinspection PyIncorrectDocstring
    def download(self, url: str, options: list[str], object_id: int) -> None:
        # noinspection PyUnresolvedReferences
        """Download given item.

        Args:
            item (dict): Python dictionary that contains two keys.
                The url and the index of the corresponding row in which
                the worker should send back the information about the
                download process.

        """
        self._data["url"] = url
        self._options = options
        self._data["index"] = object_id

    def stop_download(self) -> None:
        """Stop the download process of the worker."""
        self._downloader.stop()

    def close(self) -> None:
        """Kill the worker after stopping the download process."""
        self.stop_download()
        self._running = False

    def available(self) -> bool:
        """Return True if the worker has no job else False."""
        return self._data["url"] is None

    def has_index(self, index) -> bool:
        """Return True if index is equal to self._data['index'] else False."""
        return self._data["index"] == index

    def update_data(self, data: dict[str, Any]) -> None:
        """Update self._data from the given data."""
        if self._wait_for_reply:
            # Update data only if a receive request has been issued
            self._data.update(data)

            self._wait_for_reply = False

    @property
    def successful(self) -> int:
        """Return the number of successful downloads for current worker."""
        return self._successful

    def _reset(self) -> None:
        """Reset self._data back to the original state."""
        for key in self._data:
            self._data[key] = None

    def _log_data(self, data: str) -> None:
        """Callback method for self._downloader.

        This method is used to write the given data in a synchronized way
        to the log file using the self.log_manager.

        Args:
            data (str): String to write to the log file.

        """
        if self.log_manager is not None:
            self.log_manager.log(data)

    def _data_hook(self, data: dict[str, Any]) -> None:
        """Callback method for self._downloader.

        This method updates self._data and sends the updates back to the
        GUI using the self._talk_to_gui() method.

        Args:
            data (dict): Python dictionary which contains information
                about the download process. For more info see the
                extract_data() function under the `downloaders` module.

        """
        self._talk_to_gui("send", data)

    def _talk_to_gui(self, signal: str, data: dict[str, Any]) -> None:
        """Communicate with the GUI using wxCallAfter and Publisher.

        Send/Ask data to/from the GUI. Note that if the signal is 'receive'
        then the Worker will wait until it receives a reply from the GUI.

        Args:
            signal (str): Unique string that informs the GUI about the
                communication procedure.

            data (dict): Python dictionary which holds the data to be sent
                back to the GUI. If the signal is 'send' then the dictionary
                contains the updates for the GUI (e.g. percentage, eta). If
                the signal is 'receive' then the dictionary contains exactly
                three keys. The 'index' (row) from which we want to retrieve
                the data, the 'source' which identifies a column in the
                wxListCtrl widget and the 'dest' which tells the wxListCtrl
                under which key to store the retrieved data.

        Note:
            Worker class supports 2 signals.
                1) send: The Worker sends data back to the GUI
                         (e.g. Send status updates).
                2) receive: The Worker asks data from the GUI
                            (e.g. Receive the name of a file).

        Structure:
            ('send', {'index': <item_row>, data_to_send*})

            ('receive', {'index': <item_row>, 'source': 'source_key', 'dest': 'destination_key'})

        """
        data["index"] = self._data["index"]

        if signal == "receive":
            self._wait_for_reply = True

        if wx.GetApp() is not None:
            wx.CallAfter(
                Publisher.sendMessage, WORKER_PUB_TOPIC, signal=signal, data=data
            )

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(Worker_{self.worker})>"
