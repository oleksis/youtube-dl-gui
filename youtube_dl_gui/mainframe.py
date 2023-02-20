"""yt-dlg module responsible for the main app window. """
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Iterable

import wx
import wx.adv

# noinspection PyPep8Naming
from pubsub import pub as Publisher
from wx.lib.mixins.listctrl import ListCtrlAutoWidthMixin

from .darktheme import dark_mode
from .downloadmanager import (
    MANAGER_PUB_TOPIC,
    WORKER_PUB_TOPIC,
    DownloadItem,
    DownloadList,
    DownloadManager,
)
from .formats import AUDIO_FORMATS, DEFAULT_FORMATS, FORMATS, VIDEO_FORMATS
from .info import (
    __appname__,
    __author__,
    __descriptionfull__,
    __licensefull__,
    __maintainer__,
    __projecturl__,
)
from .logmanager import LogManager
from .optionsframe import OptionsFrame
from .optionsmanager import OptionsManager
from .parsers import OptionsParser
from .updatemanager import UPDATE_PUB_TOPIC, UpdateThread
from .utils import (
    YOUTUBEDL_BIN,
    build_command,
    get_icon_file,
    get_key,
    get_pixmaps_dir,
    get_time,
    open_file,
    shutdown_sys,
)
from .version import __version__
from .widgets import (
    ButtonsChoiceDialog,
    ClipDialog,
    ExtComboBox,
    ListBoxComboPopup,
    LogGUI,
    MessageDialog,
    ShutdownDialog,
)

_: Callable[[str], str] = wx.GetTranslation


class ListCtrl(wx.ListCtrl, ListCtrlAutoWidthMixin):

    """Custom ListCtrl widget.

    Args:
        columns (dict): See MainFrame class STATUSLIST_COLUMNS attribute.

    """

    def __init__(self, columns: dict[str, tuple[int, str, int, bool]], *args, **kwargs):
        super().__init__(*args, **kwargs)
        ListCtrlAutoWidthMixin.__init__(self)
        self.columns = columns
        self._list_index = 0
        self._map_id: dict[int, int] = {}
        self._url_list: set[str] = set()
        self._set_columns()

    def remove_row(self, row_number: int):
        self.DeleteItem(row_number)
        total = len(self._map_id)
        for row in range(row_number, total - 1):
            self._map_id[row] = self._map_id[row + 1]
        del self._map_id[total - 1]
        self._list_index -= 1

    def move_item_up(self, row_number: int):
        self._move_item(row_number, row_number - 1)

    def move_item_down(self, row_number: int):
        self._move_item(row_number, row_number + 1)

    def _move_item(self, cur_row: int, new_row: int):
        self.Freeze()
        item = self.GetItem(cur_row)
        self.DeleteItem(cur_row)

        item.SetId(new_row)
        self.InsertItem(item)
        # Swap Data associated (Python Data Mixing)
        self._map_id[new_row], self._map_id[cur_row] = (
            self._map_id[cur_row],
            self._map_id[new_row],
        )

        self.Select(new_row)
        self.Thaw()
        # self.SetFocus()

    def has_url(self, url: str):
        """Returns True if the url is aleady in the ListCtrl else False.

        Args:
            url (string): URL string.

        """
        return url in self._url_list

    def bind_item(self, download_item: DownloadItem):
        self.InsertItem(self._list_index, download_item.url)

        self.SetItemData(self._list_index, download_item.object_id)
        self._map_id[self._list_index] = download_item.object_id

        self._update_from_item(self._list_index, download_item)

        self._list_index += 1

    def GetItemData(self, row_index_selected: int) -> int | None:
        return self._map_id.get(row_index_selected, None)

    def _update_from_item(self, row: int, download_item: DownloadItem):
        progress_stats = download_item.progress_stats

        for key in self.columns:
            column = self.columns[key][0]

            if key == "status" and progress_stats["playlist_index"]:
                # Not the best place but we build the playlist status here
                status = (
                    f'{progress_stats["status"]} '
                    f'{progress_stats["playlist_index"]}/{progress_stats["playlist_size"]}'
                )

                self.SetItem(row, column, status)
            else:
                self.SetItem(row, column, progress_stats[key])

    def clear(self):
        """Clear the ListCtrl widget & reset self._list_index and
        self._url_list."""
        self.DeleteAllItems()
        self._list_index = 0
        self._url_list = set()

    def is_empty(self):
        """Returns True if the list is empty else False."""
        return self._list_index == 0

    def get_selected(self) -> int:
        return self.GetNextItem(-1, wx.LIST_NEXT_ALL, wx.LIST_STATE_SELECTED)

    def get_all_selected(self) -> list[int]:
        return [index for index in range(self._list_index) if self.IsSelected(index)]

    def deselect_all(self):
        for index in range(self._list_index):
            self.Select(index, on=0)

    def get_next_selected(self, start: int = -1, reverse: bool = False) -> int:
        if start == -1:
            start = self._list_index - 1 if reverse else 0
        elif reverse:
            start -= 1
        else:
            start += 1

        end = -1 if reverse else self._list_index
        step = -1 if reverse else 1

        return next(
            (index for index in range(start, end, step) if self.IsSelected(index)), -1
        )

    def _set_columns(self):
        """Initializes ListCtrl columns.
        See MainFrame STATUSLIST_COLUMNS attribute for more info."""
        for column_item in sorted(self.columns.values()):
            self.InsertColumn(column_item[0], column_item[1], width=wx.LIST_AUTOSIZE)

            # If the column width obtained from wxLIST_AUTOSIZE
            # is smaller than the minimum allowed column width
            # then set the column width to the minimum allowed size
            if self.GetColumnWidth(column_item[0]) < column_item[2]:
                self.SetColumnWidth(column_item[0], column_item[2])

            # Set auto-resize if enabled
            if column_item[3]:
                self.setResizeColumn(column_item[0])


class MainFrame(wx.Frame):
    """Main window class.

    This class is responsible for creating the main app window
    and binding the events.

    Attributes:
        FRAMES_MIN_SIZE (tuple): Tuple that contains the minumum width, height of the frame.

    Args:
        opt_manager (optionsmanager.OptionsManager): Object responsible for
            handling the settings.

        log_manager (logmanager.LogManager): Object responsible for handling
            the log stuff.

        _parent (wx.Window): Frame parent.

    """

    FRAMES_MIN_SIZE = (560, 360)

    def __init__(
        self,
        opt_manager: OptionsManager,
        log_manager: LogManager | None = None,
        _parent: wx.Window | None = None,
    ):
        super().__init__(
            _parent,
            wx.ID_ANY,
            __appname__,
            size=opt_manager.options.get("main_win_size", OptionsManager.MAIN_WIN_SIZE),
        )

        # Labels area: Strings for the widgets labels.
        self.URLS_LABEL = _("Enter URLs below")
        self.UPDATE_LABEL = _("Update")
        self.SETTINGS_LABEL = _("Setting")
        self.OPTIONS_LABEL = _("Options")
        self.STOP_LABEL = _("Stop")
        self.INFO_LABEL = _("Info")
        self.WELCOME_MSG = _("Welcome")
        self.WARNING_LABEL = _("Warning")
        self.ADD_LABEL = _("Add")
        self.DOWNLOAD_LIST_LABEL = _("Download list")
        self.DELETE_LABEL = _("Delete")
        self.PLAY_LABEL = _("Play")
        self.UP_LABEL = _("Up")
        self.DOWN_LABEL = _("Down")
        self.RELOAD_LABEL = _("Reload")
        self.PAUSE_LABEL = _("Pause")
        self.START_LABEL = _("Start")
        self.ABOUT_LABEL = _("About")
        self.VIEWLOG_LABEL = _("View Log")

        self.SUCC_REPORT_MSG = _(
            "Downloaded {0} URL(s) in {1} "
            "day(s) {2} hour(s) {3} minute(s) {4} second(s)"
        )
        self.DL_COMPLETED_MSG = _("Downloads completed")
        self.URL_REPORT_MSG = _(
            "Total Progress: {0:.1f}% | Queued ({1}) Paused ({2}) Active ({3}) "
            "Completed ({4}) Error ({5})"
        )
        self.CLOSING_MSG = _("Stopping downloads")
        self.CLOSED_MSG = _("Downloads stopped")
        self.PROVIDE_URL_MSG = _("You need to provide at least one URL")
        self.DOWNLOAD_STARTED = _("Downloads started")
        self.CHOOSE_DIRECTORY = _("Choose Directory")

        self.DOWNLOAD_ACTIVE = _(
            "Download in progress. Please wait for all downloads to complete"
        )
        self.UPDATE_ACTIVE = _("Update already in progress")

        self.UPDATING_MSG = _("Downloading latest CLI Backend. Please wait...")
        self.UPDATE_ERR_MSG = _("CLI Backend download failed [{0}]")
        self.UPDATE_SUCC_MSG = _("Successfully downloaded CLI Backend.")

        self.OPEN_DIR_ERR = _(
            "Unable to open directory: '{dir}'. " "The specified path does not exist"
        )
        self.SHUTDOWN_ERR = _(
            "Error while shutting down. " "Make sure you typed the correct password"
        )
        self.SHUTDOWN_MSG = _("Shutting down system")

        self.VIDEO_LABEL = _("Title")
        self.EXTENSION_LABEL = _("Extension")
        self.SIZE_LABEL = _("Size")
        self.PERCENT_LABEL = _("Percent")
        self.ETA_LABEL = _("ETA")
        self.SPEED_LABEL = _("Speed")
        self.STATUS_LABEL = _("Status")

        # STATUSLIST_COLUMNS
        #
        # Dictionary which contains the columns for the wxListCtrl widget.
        # Each key represents a column and holds informations about itself.
        # Structure informations:
        #  column_key: (column_number, column_label, minimum_width, is_resizable)
        #
        self.STATUSLIST_COLUMNS: dict[str, tuple[int, str, int, bool]] = {
            "filename": (0, self.VIDEO_LABEL, 180, True),
            "extension": (1, self.EXTENSION_LABEL, 80, False),
            "filesize": (2, self.SIZE_LABEL, 80, False),
            "percent": (3, self.PERCENT_LABEL, 80, False),
            "eta": (4, self.ETA_LABEL, 90, False),
            "speed": (5, self.SPEED_LABEL, 90, False),
            "status": (6, self.STATUS_LABEL, 90, False),
        }

        self.opt_manager = opt_manager
        self.log_manager = log_manager
        self.download_manager: DownloadManager | None = None
        self.update_thread: UpdateThread | None = None
        self.app_icon: wx.Icon | None = None

        self._download_list = DownloadList()

        # Set up youtube-dl options parser
        self._options_parser = OptionsParser()

        # Get the pixmaps directory
        self._pixmaps_path: str | None = get_pixmaps_dir()

        # Set the Timer
        self._app_timer = wx.Timer(self)

        # Set the app icon
        app_icon_path: str | None = get_icon_file()
        if app_icon_path:
            self.app_icon = wx.Icon(app_icon_path, wx.BITMAP_TYPE_PNG)
            self.SetIcon(self.app_icon)

        bitmap_data = (
            ("down", "arrow_down_32px.png"),
            ("up", "arrow_up_32px.png"),
            ("play", "camera_32px.png"),
            ("start", "cloud_download_32px.png"),
            ("delete", "delete_32px.png"),
            ("folder", "folder_32px.png"),
            ("pause", "pause_32px.png"),
            ("resume", "play_arrow_32px.png"),
            ("reload", "reload_32px.png"),
            ("settings", "settings_20px.png"),
            ("stop", "stop_32px.png"),
        )

        self._bitmaps: dict[str, wx.Bitmap] = {
            target: wx.Bitmap(str(Path(self._pixmaps_path or ".").joinpath(name)))
            for target, name in bitmap_data
        }

        # Set the data for all the wx.Button items
        # name, label, size, event_handler
        buttons_data = (
            ("delete", self.DELETE_LABEL, (-1, -1), self._on_delete, wx.BitmapButton),
            ("play", self.PLAY_LABEL, (-1, -1), self._on_play, wx.BitmapButton),
            ("up", self.UP_LABEL, (-1, -1), self._on_arrow_up, wx.BitmapButton),
            ("down", self.DOWN_LABEL, (-1, -1), self._on_arrow_down, wx.BitmapButton),
            ("reload", self.RELOAD_LABEL, (-1, -1), self._on_reload, wx.BitmapButton),
            ("pause", self.PAUSE_LABEL, (-1, -1), self._on_pause, wx.BitmapButton),
            ("start", self.START_LABEL, (-1, -1), self._on_start, wx.BitmapButton),
            (
                "settings",
                self.SETTINGS_LABEL,
                (-1, -1),
                self._on_settings,
                wx.BitmapButton,
            ),
            ("savepath", "...", (35, -1), self._on_savepath, wx.Button),
            ("add", self.ADD_LABEL, (-1, -1), self._on_add, wx.Button),
        )

        # Set the data for the settings menu item
        # label, event_handler
        settings_menu_data = (
            (self.OPTIONS_LABEL, self._on_options),
            (self.UPDATE_LABEL, self._on_update),
            (self.VIEWLOG_LABEL, self._on_viewlog),
            (self.ABOUT_LABEL, self._on_about),
        )

        statuslist_menu_data = (
            (_("Get URL"), self._on_geturl),
            (_("Get command"), self._on_getcmd),
            (_("Clip Multimedia"), self._on_clip),
            (_("Open destination"), self._on_open_dest),
            (_("Re-enter"), self._on_reenter),
        )

        # Is Dark Theme
        self._dark_mode = self.opt_manager.options.get("dark_mode", False)

        # Create options frame
        self._options_frame = OptionsFrame(self, self._dark_mode)

        # Create frame components
        self._panel = wx.Panel(self)

        self._url_text = self._create_statictext(self.URLS_LABEL)

        self._url_list = self._create_textctrl(
            wx.TE_MULTILINE | wx.TE_DONTWRAP, self._on_urllist_edit
        )

        self._folder_icon = self._create_static_bitmap(
            self._bitmaps["folder"], self._on_open_path
        )

        self._path_combobox = ExtComboBox(self._panel, 5, style=wx.CB_READONLY)

        FORMATS["0"] = _("default")
        DEFAULT_FORMATS["0"] = _("default")

        self._videoformat_combobox = wx.ComboCtrl(
            self._panel, size=(180, -1), style=wx.CB_READONLY
        )
        self._popup_ctrl = ListBoxComboPopup(
            self._videoformat_combobox, self._dark_mode
        )
        self._videoformat_combobox.SetPopupControl(self._popup_ctrl)

        self._download_text = self._create_statictext(self.DOWNLOAD_LIST_LABEL)
        self._status_list = ListCtrl(
            self.STATUSLIST_COLUMNS,
            parent=self._panel,
            style=wx.LC_REPORT | wx.LC_HRULES | wx.LC_VRULES,
        )

        # Dictionary to store all the buttons
        self._buttons = {}

        for item in buttons_data:
            name, label, size, evt_handler, parent = item

            button = parent(self._panel, size=size)

            if parent == wx.Button:
                button.SetLabel(label)
            elif parent == wx.BitmapButton:
                button.SetToolTip(wx.ToolTip(label))

            if name in self._bitmaps:
                button.SetBitmap(self._bitmaps[name], wx.TOP)

            if evt_handler is not None:
                button.Bind(wx.EVT_BUTTON, evt_handler)

            self._buttons[name] = button

        self._status_bar = self.CreateStatusBar()

        # Create extra components
        self._settings_menu = self._create_menu_item(settings_menu_data)
        self._statuslist_menu = self._create_menu_item(statuslist_menu_data)

        # Overwrite the menu hover event to avoid changing the statusbar
        self.Bind(wx.EVT_MENU_HIGHLIGHT, lambda event: None)

        # Bind extra events
        self.Bind(
            wx.EVT_LIST_ITEM_RIGHT_CLICK,
            self._on_statuslist_right_click,
            self._status_list,
        )
        self.Bind(wx.EVT_TEXT, self._update_savepath, self._path_combobox)
        self.Bind(
            wx.EVT_LIST_ITEM_SELECTED, self._update_pause_button, self._status_list
        )
        self.Bind(
            wx.EVT_LIST_ITEM_DESELECTED, self._update_pause_button, self._status_list
        )
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Bind(wx.EVT_TIMER, self._on_timer, self._app_timer)

        self._videoformat_combobox.Bind(wx.EVT_COMBOBOX, self._update_videoformat)
        self._videoformat_combobox.Bind(
            wx.EVT_COMBOBOX_CLOSEUP, self._update_videoformat
        )

        # Set threads wxCallAfter handlers
        self._set_publisher(self._update_handler, UPDATE_PUB_TOPIC)
        self._set_publisher(self._download_worker_handler, WORKER_PUB_TOPIC)
        self._set_publisher(self._download_manager_handler, MANAGER_PUB_TOPIC)

        # Set up extra stuff
        self.Center()
        self.SetMinSize(self.FRAMES_MIN_SIZE)

        self._status_bar_write(self.WELCOME_MSG)

        self._update_videoformat_combobox()
        self._path_combobox.LoadMultiple(
            self.opt_manager.options.get("save_path_dirs", [])
        )
        self._path_combobox.SetValue(self.opt_manager.options.get("save_path", "."))
        self._update_savepath(None)

        self._set_layout()
        # Set Dark Theme
        dark_mode(self._panel, self._dark_mode)
        dark_mode(self._options_frame.panel, self._dark_mode)

        if os.name == "nt":
            self._videoformat_combobox.SetForegroundColour("Black")

        self._url_list.SetFocus()

    @staticmethod
    def _create_menu_item(items: Iterable[tuple[str, Any]]) -> wx.Menu:
        menu = wx.Menu()

        for label, evt_handler in items:
            menu_item = menu.Append(-1, label)

            menu.Bind(wx.EVT_MENU, evt_handler, menu_item)

        return menu

    def _on_statuslist_right_click(self, event):
        selected = event.GetIndex()

        if selected != -1:
            self._status_list.deselect_all()
            self._status_list.Select(selected, on=1)

            self.PopupMenu(self._statuslist_menu)

    # noinspection PyUnusedLocal
    def _on_reenter(self, event):
        selected = self._status_list.get_selected()

        if selected != -1:
            object_id: int | None = self._status_list.GetItemData(selected)
            download_item = self._download_list.get_item(object_id)

            if download_item and download_item.stage != "Active":
                self._status_list.remove_row(selected)
                self._download_list.remove(object_id)

                options = self._options_parser.parse(self.opt_manager.options)

                download_item = DownloadItem(download_item.url, options)
                download_item.path = self.opt_manager.options["save_path"]

                if not self._download_list.has_item(download_item.object_id):
                    self._status_list.bind_item(download_item)
                    self._download_list.insert(download_item)

    def reset(self):
        self._update_videoformat_combobox()
        self._path_combobox.LoadMultiple(self.opt_manager.options["save_path_dirs"])
        self._path_combobox.SetValue(self.opt_manager.options["save_path"])

    # noinspection PyUnusedLocal
    def _on_open_dest(self, event):
        selected = self._status_list.get_selected()

        if selected != -1:
            object_id = self._status_list.GetItemData(selected)
            download_item = self._download_list.get_item(object_id)

            if download_item.path:
                open_file(download_item.path)

    # noinspection PyUnusedLocal
    def _on_open_path(self, event):
        open_file(self._path_combobox.GetValue())

    def _copy_to_clipboard(self, text: str):
        clipdata = wx.TextDataObject()
        clipdata.SetText(text)
        wx.TheClipboard.Open()
        wx.TheClipboard.SetData(clipdata)
        wx.TheClipboard.Close()

    # noinspection PyUnusedLocal
    def _on_geturl(self, event):
        selected = self._status_list.get_selected()

        if selected != -1:
            object_id = self._status_list.GetItemData(selected)
            download_item = self._download_list.get_item(object_id)

            url = download_item.url

            if not wx.TheClipboard.IsOpened():
                self._copy_to_clipboard(url)

    # noinspection PyUnusedLocal
    def _on_getcmd(self, event):
        selected = self._status_list.get_selected()

        if selected != -1:
            object_id = self._status_list.GetItemData(selected)
            download_item = self._download_list.get_item(object_id)

            cmd = build_command(
                download_item.options,
                download_item.url,
                self.opt_manager.options.get("cli_backend", YOUTUBEDL_BIN),
            )

            if not wx.TheClipboard.IsOpened():
                self._copy_to_clipboard(cmd)

    def _on_clip(self, event):
        """
        Add external downloader args options
        to the end of the list options if ID_OK
        """
        index = self._status_list.get_next_selected()

        if index != -1:
            object_id = self._status_list.GetItemData(index)
            selected_download_item: DownloadItem = self._download_list.get_item(
                object_id
            )

            if selected_download_item.stage == "Active":
                self._create_popup(
                    _("Item is active, can not set the multimedia clip"),
                    self.WARNING_LABEL,
                    wx.OK | wx.ICON_EXCLAMATION,
                )
                return

            dlg = ClipDialog(self, selected_download_item, self._dark_mode)
            check_options = dlg.CHECK_OPTIONS

            result = dlg.ShowModal() == wx.ID_OK

            clip_start: wx.TimeSpan = dlg.clip_start.GetValue(as_wxTimeSpan=True)
            clip_end: wx.TimeSpan = dlg.clip_end.GetValue(as_wxTimeSpan=True)

            dlg.Destroy()

            if result:
                selected_download_item.options.extend(
                    (
                        f"{check_options[0]}",
                        "ffmpeg",
                        f"{check_options[1]}",
                        f"-ss {clip_start.GetSeconds()} -to {clip_end.GetSeconds()}",
                    )
                )

    # noinspection PyUnusedLocal
    def _on_timer(self, event):
        total_percentage = 0.0
        queued = paused = active = completed = error = 0

        for item in self._download_list.get_items():
            if item.stage == "Active":
                active += 1
                total_percentage += float(item.progress_stats["percent"].split("%")[0])
            elif item.stage == "Completed":
                completed += 1
            elif item.stage == "Error":
                error += 1
            elif item.stage == "Paused":
                paused += 1
            elif item.stage == "Queued":
                queued += 1
        # REFACTOR Store percentage as float in the DownloadItem?
        # REFACTOR DownloadList keep track for each item stage?

        items_count = active + completed + error + queued
        total_percentage += completed * 100.0 + error * 100.0

        if items_count:
            total_percentage /= items_count

        msg = self.URL_REPORT_MSG.format(
            total_percentage, queued, paused, active, completed, error
        )

        if self.update_thread is None:
            # Dont overwrite the update messages
            self._status_bar_write(msg)

    # noinspection PyUnusedLocal
    def _update_pause_button(self, event):
        selected_rows = self._status_list.get_all_selected()

        label = _("Pause")
        bitmap = self._bitmaps["pause"]

        for row in selected_rows:
            object_id = self._status_list.GetItemData(row)
            download_item = self._download_list.get_item(object_id)

            if download_item.stage == "Paused":
                # If we find one or more items in Paused
                # state set the button functionality to resume
                label = _("Resume")
                bitmap = self._bitmaps["resume"]
                break

        self._buttons["pause"].SetLabel(label)
        self._buttons["pause"].SetToolTip(wx.ToolTip(label))
        self._buttons["pause"].SetBitmap(bitmap, wx.TOP)

    def _get_listbox_headers(self):
        lb_popup_ctr: ListBoxComboPopup = self._popup_ctrl
        return lb_popup_ctr.GetControl()

    def _update_videoformat_combobox(self):
        lb_headers = self._get_listbox_headers()
        lb_headers.Clear()

        lb_headers.add_items(list(DEFAULT_FORMATS.values()), False)

        vformats: list[str] = [
            FORMATS[get_key(vformat, FORMATS)]
            for vformat in self.opt_manager.options.get("selected_video_formats", [])
        ]

        aformats: list[str] = [
            FORMATS[get_key(aformat, FORMATS)]
            for aformat in self.opt_manager.options.get("selected_audio_formats", [])
        ]

        if vformats:
            lb_headers.add_header(_("Video"))
            lb_headers.add_items(vformats)

        if aformats:
            lb_headers.add_header(_("Audio"))
            lb_headers.add_items(aformats)

        current_index = lb_headers.FindString(
            FORMATS[self.opt_manager.options.get("selected_format", "")]
        )

        if current_index == wx.NOT_FOUND:
            lb_headers.SetSelection(0)
        else:
            lb_headers.SetSelection(current_index)

        self._popup_ctrl.value = lb_headers.GetSelection()

        self._update_videoformat(None)

    # noinspection PyUnusedLocal
    def _update_videoformat(self, event):
        lb_headers = self._get_listbox_headers()
        selection = lb_headers.GetStringSelection()
        selected_format = get_key(selection, FORMATS, "0")
        self.opt_manager.options["selected_format"] = selected_format

        if selected_format in VIDEO_FORMATS:
            self.opt_manager.options["video_format"] = selected_format
            self.opt_manager.options[
                "audio_format"
            ] = ""  # NOTE Set to default value, check parsers.py
        elif selected_format in AUDIO_FORMATS:
            self.opt_manager.options["video_format"] = "0"
            self.opt_manager.options["audio_format"] = selected_format
        else:
            self.opt_manager.options["video_format"] = "0"
            self.opt_manager.options["audio_format"] = ""

        self._videoformat_combobox.SetText(FORMATS[selected_format])

    # noinspection PyUnusedLocal
    def _update_savepath(self, event):
        try:
            path: Path = Path(self._path_combobox.GetValue()).resolve()
            if not path.exists():
                os.makedirs(str(path))
        except OSError:
            # Avoid [WinError 433] Driver removed ?!
            path: Path = Path().home() / Path("Videos")
            self._path_combobox.SetValue(str(path))

        self.opt_manager.options["save_path"] = str(path)

    # noinspection PyUnusedLocal
    def _on_delete(self, event):
        index = self._status_list.get_next_selected()

        if index == -1:
            dlg = ButtonsChoiceDialog(
                self,
                [_("Remove all"), _("Remove completed")],
                _("No items selected. Please pick an action"),
                _("Delete"),
                self._dark_mode,
            )

            ret_code = dlg.ShowModal()
            dlg.Destroy()

            # REFACTOR Maybe add this functionality directly to DownloadList?
            if ret_code == 1:
                for ditem in self._download_list.get_items():
                    if ditem.stage != "Active":
                        self._status_list.remove_row(
                            self._download_list.index(ditem.object_id)
                        )
                        self._download_list.remove(ditem.object_id)

            if ret_code == 2:
                for ditem in self._download_list.get_items():
                    if ditem.stage == "Completed":
                        self._status_list.remove_row(
                            self._download_list.index(ditem.object_id)
                        )
                        self._download_list.remove(ditem.object_id)
        else:
            result = True

            if self.opt_manager.options.get("confirm_deletion", True):
                dlg = MessageDialog(
                    self,
                    _("Are you sure you want to remove selected items?"),
                    _("Delete"),
                    self._dark_mode,
                )

                result = dlg.ShowModal() == wx.ID_YES
                dlg.Destroy()

            if result:
                while index >= 0:
                    object_id = self._status_list.GetItemData(index)
                    selected_download_item = self._download_list.get_item(object_id)

                    if selected_download_item.stage == "Active":
                        self._create_popup(
                            _("Item is active, cannot remove"),
                            self.WARNING_LABEL,
                            wx.OK | wx.ICON_EXCLAMATION,
                        )
                    else:
                        self._status_list.remove_row(index)
                        self._download_list.remove(object_id)
                        index -= 1

                    index = self._status_list.get_next_selected(index)

        self._update_pause_button(None)

    # noinspection PyUnusedLocal
    def _on_play(self, event):
        selected_rows = self._status_list.get_all_selected()

        if selected_rows:
            for selected_row in selected_rows:
                object_id = self._status_list.GetItemData(selected_row)
                selected_download_item = self._download_list.get_item(object_id)

                if selected_download_item.stage == "Completed":
                    if selected_download_item.filenames:
                        filename = selected_download_item.get_files()[-1]
                        open_file(filename)
                else:
                    self._create_popup(
                        _("Item is not completed"),
                        self.INFO_LABEL,
                        wx.OK | wx.ICON_INFORMATION,
                    )

    # noinspection PyUnusedLocal,PyProtectedMember
    def _on_arrow_up(self, event):
        index = self._status_list.get_next_selected()

        if index != -1:
            while index >= 0:
                object_id: int | None = self._status_list.GetItemData(index)
                download_item = self._download_list.get_item(object_id)

                assert object_id is not None
                assert download_item is not None

                new_index = index - 1
                new_index = max(new_index, 0)

                if not self._status_list.IsSelected(new_index):
                    self._download_list.move_up(object_id)
                    self._status_list.move_item_up(index)
                    self._status_list._update_from_item(new_index, download_item)

                index = self._status_list.get_next_selected(index)

    # noinspection PyUnusedLocal,PyProtectedMember
    def _on_arrow_down(self, event):
        index = self._status_list.get_next_selected(reverse=True)

        if index != -1:
            while index >= 0:
                object_id: int | None = self._status_list.GetItemData(index)
                download_item = self._download_list.get_item(object_id)

                assert object_id is not None
                assert download_item is not None

                new_index = index + 1
                if new_index >= self._status_list.GetItemCount():
                    new_index = self._status_list.GetItemCount() - 1

                if not self._status_list.IsSelected(new_index):
                    self._download_list.move_down(object_id)
                    self._status_list.move_item_down(index)
                    self._status_list._update_from_item(new_index, download_item)

                index = self._status_list.get_next_selected(index, True)

    # noinspection PyUnusedLocal,PyProtectedMember
    def _on_reload(self, event):
        selected_rows = self._status_list.get_all_selected()

        if not selected_rows:
            for index, download_item in enumerate(self._download_list.get_items()):
                if download_item.stage in ("Paused", "Completed", "Error"):
                    # Store the old savepath because reset is going to remove it
                    savepath = download_item.path
                    download_item.reset()
                    download_item.path = savepath
                    self._status_list._update_from_item(index, download_item)
        else:
            for selected_row in selected_rows:
                object_id: int | None = self._status_list.GetItemData(selected_row)
                download_item = self._download_list.get_item(object_id)

                assert download_item is not None

                if download_item.stage in ("Paused", "Completed", "Error"):
                    # Store the old savepath because reset is going to remove it
                    savepath = download_item.path
                    download_item.reset()
                    download_item.path = savepath
                    self._status_list._update_from_item(selected_row, download_item)

            self._update_pause_button(None)

    # noinspection PyUnusedLocal,PyProtectedMember
    def _on_pause(self, event):
        selected_rows = self._status_list.get_all_selected()

        if selected_rows:
            # REFACTOR Use widgets.DoubleStageButton for this and check stage
            if self._buttons["pause"].GetLabel() == _("Pause"):
                new_state = "Paused"
            else:
                new_state = "Queued"

            for selected_row in selected_rows:
                object_id: int | None = self._status_list.GetItemData(selected_row)
                download_item = self._download_list.get_item(object_id)

                assert object_id is not None
                assert download_item is not None

                if download_item.stage in ["Queued", "Paused"]:
                    self._download_list.change_stage(object_id, new_state)

                self._status_list._update_from_item(selected_row, download_item)

            self._update_pause_button(None)

    # noinspection PyUnusedLocal
    def _on_start(self, event):
        if self.download_manager is None:
            if self.update_thread is not None and self.update_thread.is_alive():
                self._create_popup(
                    _("Update in progress. Please wait for the update to complete"),
                    self.WARNING_LABEL,
                    wx.OK | wx.ICON_EXCLAMATION,
                )
            else:
                self._start_download()
        else:
            self.download_manager.stop_downloads()

    # noinspection PyUnusedLocal
    def _on_savepath(self, event):
        dlg = wx.DirDialog(
            self, self.CHOOSE_DIRECTORY, self._path_combobox.GetStringSelection()
        )

        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()

            self._path_combobox.Append(path)
            self._path_combobox.SetValue(path)
            self._update_savepath(None)

        dlg.Destroy()

    # noinspection PyUnusedLocal
    def _on_add(self, event):
        urls = self._get_urls()

        if not urls:
            self._create_popup(
                self.PROVIDE_URL_MSG, self.WARNING_LABEL, wx.OK | wx.ICON_EXCLAMATION
            )
        else:
            self._url_list.Clear()
            options = self._options_parser.parse(self.opt_manager.options)

            for url in urls:
                download_item = DownloadItem(url, options)
                download_item.path = self.opt_manager.options.get("save_path", ".")

                if not self._download_list.has_item(download_item.object_id):
                    self._status_list.bind_item(download_item)
                    self._download_list.insert(download_item)

    def _on_settings(self, event):
        event_object_pos = event.EventObject.GetPosition()
        event_object_height = event.EventObject.GetSize()[1]
        event_object_pos = (
            event_object_pos[0],
            event_object_pos[1] + event_object_height,
        )
        self.PopupMenu(self._settings_menu, event_object_pos)

    # noinspection PyUnusedLocal
    def _on_viewlog(self, event):
        if self.log_manager is None:
            self._create_popup(
                _("Logging is disabled"),
                self.WARNING_LABEL,
                wx.OK | wx.ICON_EXCLAMATION,
            )
        else:
            log_window = LogGUI(self)
            log_window.load(self.log_manager.log_file)
            log_window.Show()

    # noinspection PyUnusedLocal
    def _on_about(self, event):
        info = wx.adv.AboutDialogInfo()

        if self.app_icon is not None:
            info.SetIcon(self.app_icon)

        info.SetName(__appname__)
        info.SetVersion(__version__)
        info.SetDescription(__descriptionfull__)
        info.SetWebSite(__projecturl__)
        info.SetLicense(__licensefull__)
        info.AddDeveloper(
            __author__
            + "\n"
            + __maintainer__
            + "\n"
            + "see AUTHORS file for the complete list."
        )

        wx.adv.AboutBox(info)

    @staticmethod
    def _set_publisher(handler: Callable, topic: str):
        """Sets a handler for the given topic.

        Args:
            handler (function): Can be any function with one parameter
                the message that the caller sends.

            topic (string): Can be any string that identifies the caller.
                You can bind multiple handlers on the same topic or
                multiple topics on the same handler.

        """
        Publisher.subscribe(handler, topic)

    def _create_statictext(self, label):
        return wx.StaticText(self._panel, label=label)

    def _create_bitmap_button(self, icon, size=(-1, -1), handler=None):
        button = wx.BitmapButton(
            self._panel, bitmap=icon, size=size, style=wx.NO_BORDER
        )

        if handler is not None:
            button.Bind(wx.EVT_BUTTON, handler)

        return button

    def _create_static_bitmap(self, icon, event_handler=None):
        static_bitmap = wx.StaticBitmap(self._panel, bitmap=icon)

        if event_handler is not None:
            static_bitmap.Bind(wx.EVT_LEFT_DCLICK, event_handler)

        return static_bitmap

    def _create_textctrl(self, style=None, event_handler=None):
        if style is None:
            textctrl = wx.TextCtrl(self._panel)
        else:
            textctrl = wx.TextCtrl(self._panel, style=style)

        if event_handler is not None:
            textctrl.Bind(wx.EVT_TEXT_PASTE, event_handler)
            textctrl.Bind(wx.EVT_MIDDLE_DOWN, event_handler)

        if os.name == "nt":
            # Enable CTRL+A on Windows
            def win_ctrla_eventhandler(event):
                if event.GetKeyCode() == wx.WXK_CONTROL_A:
                    event.GetEventObject().SelectAll()

                event.Skip()

            textctrl.Bind(wx.EVT_CHAR, win_ctrla_eventhandler)

        return textctrl

    @staticmethod
    def _create_popup(text, title, style):
        wx.MessageBox(text, title, style)

    def _set_layout(self):
        """Sets the layout of the main window."""
        main_sizer = wx.BoxSizer()
        panel_sizer = wx.BoxSizer(wx.VERTICAL)

        top_sizer = wx.BoxSizer(wx.HORIZONTAL)
        top_sizer.Add(self._url_text, 0, wx.ALIGN_BOTTOM | wx.BOTTOM, 5)
        top_sizer.AddStretchSpacer(1)
        top_sizer.Add(self._buttons["settings"])
        panel_sizer.Add(top_sizer, 0, wx.EXPAND | wx.BOTTOM, 5)

        panel_sizer.Add(self._url_list, 1, wx.EXPAND)

        mid_sizer = wx.BoxSizer(wx.HORIZONTAL)
        mid_sizer.Add(self._folder_icon)
        mid_sizer.AddSpacer(3)
        mid_sizer.Add(self._path_combobox, 2, wx.ALIGN_CENTER_VERTICAL)
        mid_sizer.AddSpacer(5)
        mid_sizer.Add(self._buttons["savepath"], flag=wx.ALIGN_CENTER_VERTICAL)
        mid_sizer.AddStretchSpacer(1)
        mid_sizer.Add(self._videoformat_combobox, 0, wx.ALIGN_CENTER_VERTICAL)
        mid_sizer.AddSpacer(5)
        mid_sizer.Add(self._buttons["add"], flag=wx.ALIGN_CENTER_VERTICAL)
        panel_sizer.Add(mid_sizer, 0, wx.EXPAND | wx.TOP | wx.BOTTOM, 10)

        panel_sizer.Add(self._download_text, 0, wx.BOTTOM, 5)
        panel_sizer.Add(self._status_list, 2, wx.EXPAND)

        bottom_sizer = wx.BoxSizer(wx.HORIZONTAL)
        bottom_sizer.Add(self._buttons["delete"])
        bottom_sizer.AddSpacer(5)
        bottom_sizer.Add(self._buttons["play"])
        bottom_sizer.AddSpacer(5)
        bottom_sizer.Add(self._buttons["up"])
        bottom_sizer.AddSpacer(5)
        bottom_sizer.Add(self._buttons["down"])
        bottom_sizer.AddSpacer(5)
        bottom_sizer.Add(self._buttons["reload"])
        bottom_sizer.AddSpacer(5)
        bottom_sizer.Add(self._buttons["pause"])
        bottom_sizer.AddStretchSpacer(1)
        bottom_sizer.Add(self._buttons["start"])
        panel_sizer.Add(bottom_sizer, 0, wx.EXPAND | wx.TOP, 5)

        main_sizer.Add(panel_sizer, 1, wx.ALL | wx.EXPAND, 10)

        self._panel.SetSizer(main_sizer)
        self._panel.Layout()

    def _update_youtubedl(self):
        """Update youtube-dl binary to the latest version."""
        if self.download_manager is not None and self.download_manager.is_alive():
            self._create_popup(
                self.DOWNLOAD_ACTIVE, self.WARNING_LABEL, wx.OK | wx.ICON_EXCLAMATION
            )
        elif self.update_thread is not None and self.update_thread.is_alive():
            self._create_popup(
                self.UPDATE_ACTIVE, self.INFO_LABEL, wx.OK | wx.ICON_INFORMATION
            )
        else:
            self.update_thread = UpdateThread(self.opt_manager)

    def _status_bar_write(self, msg: str):
        """Display msg in the status bar."""
        self._status_bar.SetStatusText(msg)

    def _reset_widgets(self):
        """Resets GUI widgets after update or download process."""
        self._buttons["start"].SetLabel(self.START_LABEL)
        self._buttons["start"].SetToolTip(wx.ToolTip(self.START_LABEL))
        self._buttons["start"].SetBitmap(self._bitmaps["start"], wx.TOP)

    def _print_stats(self):
        """Display download stats in the status bar."""
        suc_downloads = self.download_manager.successful
        dtime = get_time(self.download_manager.time_it_took)

        msg = self.SUCC_REPORT_MSG.format(
            suc_downloads,
            dtime["days"],
            dtime["hours"],
            dtime["minutes"],
            dtime["seconds"],
        )

        self._status_bar_write(msg)

    def _after_download(self):
        """Run tasks after download process has been completed.

        Note:
            Here you can add any tasks you want to run after the
            download process has been completed.

        """
        if self.opt_manager.options.get("shutdown", False):
            dlg = ShutdownDialog(
                self, 60, _("Shutting down in {0} second(s)"), _("Shutdown")
            )
            result = dlg.ShowModal() == wx.ID_OK
            dlg.Destroy()

            if result:
                self.opt_manager.save_to_file()
                success = shutdown_sys(
                    self.opt_manager.options.get("sudo_password", "")
                )

                if success:
                    self._status_bar_write(self.SHUTDOWN_MSG)
                else:
                    self._status_bar_write(self.SHUTDOWN_ERR)
        elif self.opt_manager.options["show_completion_popup"]:
            self._create_popup(
                self.DL_COMPLETED_MSG, self.INFO_LABEL, wx.OK | wx.ICON_INFORMATION
            )

    # noinspection PyUnusedLocal,PyProtectedMember
    def _download_worker_handler(self, signal: str, data: dict[str, Any] | None = None):
        """downloadmanager.Worker thread handler.

        Handles messages from the Worker thread.

        Args:
            See downloadmanager.Worker _talk_to_gui() method.

        """

        download_item: DownloadItem | None = self._download_list.get_item(data["index"])

        assert download_item is not None
        assert data is not None

        download_item.update_stats(data)
        row = self._download_list.index(data["index"])
        self._status_list._update_from_item(row, download_item)

    # noinspection PyUnusedLocal
    def _download_manager_handler(
        self, signal: str, data: dict[str, str] | None = None
    ):
        """downloadmanager.DownloadManager thread handler.

        Handles messages from the DownloadManager thread.

        Args:
            See downloadmanager.DownloadManager _talk_to_gui() method.

        """
        # TODO: REFACTOR Manage better the signal stage

        if signal == "closed":
            self._status_bar_write(self.CLOSED_MSG)
            self._reset_widgets()
            self.download_manager = None
            self._app_timer.Stop()
        elif signal == "closing":
            self._status_bar_write(self.CLOSING_MSG)
        elif signal == "finished":
            self._print_stats()
            self._reset_widgets()
            self.download_manager = None
            self._app_timer.Stop()
            self._after_download()
            # NOTE Remove from here and downloadmanager
            # since now we have the wx.Timer to check progress

    def _update_handler(self, signal: str, data: list[str] = None):
        """updatemanager.UpdateThread thread handler.

        Handles messages from the UpdateThread thread.

        Args:
            See updatemanager.UpdateThread _talk_to_gui() method.

        """

        if signal == "download":
            self._status_bar_write(self.UPDATING_MSG)
        elif signal == "error":
            self._status_bar_write(self.UPDATE_ERR_MSG.format(data))
        elif signal == "correct":
            self._status_bar_write(self.UPDATE_SUCC_MSG)
        else:
            self._reset_widgets()
            self.update_thread = None

    def _get_urls(self) -> list[str]:
        """Returns urls list."""
        return [line for line in self._url_list.GetValue().split("\n") if line]

    def _start_download(self):
        if self._status_list.is_empty():
            self._create_popup(
                _("No items to download"),
                self.WARNING_LABEL,
                wx.OK | wx.ICON_EXCLAMATION,
            )
        else:
            self._app_timer.Start(100)
            self.download_manager = DownloadManager(
                self, self._download_list, self.opt_manager, self.log_manager
            )

            self._status_bar_write(self.DOWNLOAD_STARTED)
            self._buttons["start"].SetLabel(self.STOP_LABEL)
            self._buttons["start"].SetToolTip(wx.ToolTip(self.STOP_LABEL))
            self._buttons["start"].SetBitmap(self._bitmaps["stop"], wx.TOP)

    def _paste_from_clipboard(self):
        """Paste the content of the clipboard to the self._url_list widget.
        It also adds a new line at the end of the data if not exist.

        """
        if (
            not wx.TheClipboard.IsOpened()
            and wx.TheClipboard.Open()
            and wx.TheClipboard.IsSupported(wx.DataFormat(wx.DF_UNICODETEXT))
        ):
            data = wx.TextDataObject()
            wx.TheClipboard.GetData(data)

            data = data.GetText()

            if data != "" and data[-1] != "\n":
                data += "\n"

            self._url_list.WriteText(data)

            wx.TheClipboard.Close()

    def _on_urllist_edit(self, event):
        """Event handler of the self._url_list widget.

        This method is triggered when the users pastes text into
        the URLs list either by using CTRL+V or by using the middle
        click of the mouse.

        """
        if event.GetEventType() == wx.EVT_TEXT_PASTE.typeId:
            self._paste_from_clipboard()
        else:
            wx.TheClipboard.UsePrimarySelection(True)
            self._paste_from_clipboard()
            wx.TheClipboard.UsePrimarySelection(False)

    # noinspection PyUnusedLocal
    def _on_update(self, event):
        """Event handler of the self._update_btn widget.

        This method is used when the update button is pressed to start
        the update process.

        Note:
            Currently there is not way to stop the update process.

        """
        if self.opt_manager.options.get("disable_update", False):
            self._create_popup(
                _(
                    "Updates are disabled for your system. "
                    "Please use the system's package manager to update the CLI Backend."
                ),
                self.INFO_LABEL,
                wx.OK | wx.ICON_INFORMATION,
            )
        else:
            self._update_youtubedl()

    # noinspection PyUnusedLocal
    def _on_options(self, event):
        """Event handler of the self._options_btn widget.

        This method is used when the options button is pressed to show
        the options window.

        """
        self._options_frame.load_all_options()
        self._options_frame.Show()

    # noinspection PyUnusedLocal
    def _on_close(self, event):
        """Event handler for the wx.EVT_CLOSE event.

        This method is used when the user tries to close the program
        to save the options and make sure that the download & update
        processes are not running.

        """
        result = True

        if self.opt_manager.options.get("confirm_exit", True):
            dlg = MessageDialog(
                self,
                _("Are you sure you want to exit?"),
                _("Exit"),
                self._dark_mode,
            )

            result = dlg.ShowModal() == wx.ID_YES
            dlg.Destroy()

        if result:
            self.close()

    def close(self):
        if self.download_manager:
            self.download_manager.stop_downloads()
            self.download_manager.join()

        if self.update_thread:
            self.update_thread.join()

        # Store main-options frame size
        self.opt_manager.options["main_win_size"] = self.GetSize()
        self.opt_manager.options["opts_win_size"] = self._options_frame.GetSize()

        self.opt_manager.options["save_path_dirs"] = self._path_combobox.GetStrings()

        self._options_frame.save_all_options()
        self.opt_manager.save_to_file()

        self.Destroy()
