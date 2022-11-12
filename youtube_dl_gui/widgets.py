# type: ignore[misc]
"""Custom widgets for yt-dlg"""

from __future__ import annotations

import contextlib
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import wx
import wx.lib.masked as masked

from .darktheme import DARK_BACKGROUND_COLOUR, DARK_FOREGROUND_COLOUR, dark_mode
from .utils import IS_WINDOWS

if TYPE_CHECKING:
    from .downloadmanager import DownloadItem
    from .mainframe import MainFrame
    from .optionsframe import OptionsFrame

_: Callable[[str], str] = wx.GetTranslation


def crt_command_event(event: wx.PyEventBinder, event_id: int = 0) -> wx.CommandEvent:
    """Shortcut to create command events."""
    return wx.CommandEvent(event.typeId, event_id)


# noinspection PyUnresolvedReferences,PyPep8Naming
class ListBoxWithHeaders(wx.ListBox):
    """Custom ListBox object that supports 'headers'.

    Attributes:
        NAME (str): Default name for the name argument of the __init__.

        TEXT_PREFIX (str): Text to add before normal items in order to
            distinguish them (normal items) from headers.

        EVENTS (list): List with events to overwrite to avoid header selection.

    """

    NAME = "listBoxWithHeaders"

    TEXT_PREFIX = "    "

    EVENTS: list[wx.PyEventBinder] = [
        wx.EVT_LEFT_DOWN,
        wx.EVT_LEFT_DCLICK,
        wx.EVT_RIGHT_DOWN,
        wx.EVT_RIGHT_DCLICK,
        wx.EVT_MIDDLE_DOWN,
        wx.EVT_MIDDLE_DCLICK,
    ]

    # noinspection PyShadowingBuiltins
    def __init__(
        self,
        parent,
        id=wx.ID_ANY,
        pos=wx.DefaultPosition,
        size=wx.DefaultSize,
        choices=None,
        style=0,
        validator=wx.DefaultValidator,
        name=NAME,
    ) -> None:
        if choices is None:
            choices = []
        super().__init__(parent, id, pos, size, choices, style, validator, name)
        self.__headers: set[str] = set()

        # Ignore all key events i'm bored to handle the header selection
        self.Bind(wx.EVT_KEY_DOWN, lambda event: None)

        # Make sure that a header is never selected
        self.Bind(wx.EVT_LISTBOX, self._on_listbox)
        for _event in self.EVENTS:
            self.Bind(_event, self._disable_header_selection)

        # Append the items in our own way in order to add the TEXT_PREFIX
        self.AppendItems(choices)

    def _disable_header_selection(self, event) -> None:
        """Stop event propagation if the selected item is a header."""
        row = self.HitTest(event.GetPosition())
        event_skip = row == wx.NOT_FOUND or self.GetString(row) not in self.__headers
        event.Skip(event_skip)

    def _on_listbox(self, event) -> None:
        """Make sure no header is selected."""
        if event.GetString() in self.__headers:
            self.Deselect(event.GetSelection())
        event.Skip()

    def _add_prefix(self, string: str) -> str:
        return self.TEXT_PREFIX + string

    def _remove_prefix(self, string: str) -> str:
        if string[: len(self.TEXT_PREFIX)] == self.TEXT_PREFIX:
            return string[len(self.TEXT_PREFIX) :]
        return string

    # wx.ListBox methods

    def FindString(self, string: str, **kwargs) -> int:
        index = super().FindString(string, **kwargs)

        if index == wx.NOT_FOUND:
            # This time try with prefix
            index = super().FindString(self._add_prefix(string), **kwargs)

        return index

    def GetStringSelection(self) -> str:
        return self._remove_prefix(super().GetStringSelection())

    def GetString(self, index: int) -> str:
        if index < 0 or index >= self.GetCount():
            # Return empty string based on the wx.ListBox docs
            # for some reason parent GetString does not handle
            # invalid indices
            return ""

        return self._remove_prefix(super().GetString(index))

    def InsertItems(self, items: list[str], pos: int) -> None:
        items = [self._add_prefix(item) for item in items]
        super().InsertItems(items, pos)

    def SetSelection(self, index: int) -> None:
        if self.GetString(index) in self.__headers:
            self.Deselect(self.GetSelection())
        else:
            super().SetSelection(index)

    def SetString(self, index: int, string: str) -> None:
        old_string = self.GetString(index)

        if old_string in self.__headers and string != old_string:
            self.__headers.remove(old_string)
            self.__headers.add(string)

        super().SetString(index, string)

    def SetStringSelection(self, string: str) -> bool:
        if string in self.__headers:
            return False

        self.SetSelection(
            self.FindString(
                string,
            )
        )
        return True

    # wx.ItemContainer methods

    def AppendItems(self, strings: list[str], with_prefix: bool = True) -> None:
        if with_prefix:
            strings = [self._add_prefix(string) for string in strings]

        super().AppendItems(strings)

    def Clear(self) -> None:
        self.__headers.clear()
        super().Clear()

    def Delete(self, index: int) -> None:
        string: str = self.GetString(index)

        if string in self.__headers:
            self.__headers.remove(string)

        super().Delete(index)

    # Extra methods

    def add_header(self, header_string: str) -> int:
        self.__headers.add(header_string)
        return super().Append(header_string)

    def add_item(
        self,
        item: str,
        with_prefix: bool = True,
        clientData: dict[str, str] | None = None,
    ) -> None:
        if with_prefix:
            item = self._add_prefix(item)

        super().Append(item, clientData)

    def add_items(self, items: list[str], with_prefix: bool = True) -> None:
        for item in items:
            self.add_item(item, with_prefix)


# noinspection PyPep8Naming
class ListBoxComboPopup(wx.ComboPopup):
    """ListBoxWithHeaders as a popup"""

    def __init__(
        self, parent: wx.ComboCtrl | None = None, darkmode: bool = False
    ) -> None:
        super().__init__()
        self.__parent = parent
        self.__listbox: ListBoxWithHeaders | None = None
        self.__dark_mode: bool = darkmode
        self.value = -1

    def _on_motion(self, event) -> None:
        row: int = self.__listbox.HitTest(event.GetPosition())

        if row != wx.NOT_FOUND:
            self.__listbox.SetSelection(row)

            self.curitem = row if self.__listbox.IsSelected(row) else wx.NOT_FOUND

    # noinspection PyUnusedLocal
    def _on_left_down(self, event) -> None:
        self.value = self.curitem
        if self.value >= 0:
            self.Dismiss()

    # wx.ComboPopup methods

    # noinspection PyAttributeOutsideInit
    def Init(self) -> None:
        self.value = self.curitem = -1

    def Create(self, parent: wx.ComboCtrl, **kwargs) -> bool:
        # Create components
        self.__listbox = ListBoxWithHeaders(parent, style=wx.LB_SINGLE)

        if self.__dark_mode:
            self.__listbox.SetBackgroundColour(DARK_BACKGROUND_COLOUR)
            self.__listbox.SetForegroundColour(DARK_FOREGROUND_COLOUR)

        self.__listbox.Bind(wx.EVT_MOTION, self._on_motion)
        self.__listbox.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)

        return True

    def GetControl(self) -> ListBoxWithHeaders | None:
        return self.__listbox

    def AddItem(
        self,
        item: str,
        with_prefix: bool = True,
        clientData: dict[str, str] | None = None,
    ) -> None:
        self.__listbox.add_item(item, with_prefix, clientData)

    def AddItems(self, items: list[str], with_prefix: bool = True) -> None:
        self.__listbox.add_items(items, with_prefix)

    def GetStringValue(self) -> str:
        return self.__listbox.GetString(self.value)

    def GetSelection(self) -> int:
        return self.value

    def SetSelection(self, index: int) -> None:
        self.__listbox.SetSelection(index)

        if self.__listbox.IsSelected(index):
            self.value = index
            self.__parent.SetValue(self.GetStringValue())

    def SetStringSelection(self, string: str) -> None:
        index: int = self.__listbox.FindString(
            string,
        )
        self.__listbox.SetSelection(index)

        if index != wx.NOT_FOUND and self.__listbox.GetSelection() == index:
            self.value = index
            self.SetSelection(self.value)

    def Clear(self) -> None:
        self.__parent.SetValue("")
        self.__listbox.Clear()

    def IsListEmpty(self) -> bool:
        return self.__listbox.GetCount() == 0

    def OnDismiss(self) -> None:
        if self.value < 0:
            self.value = 0
            self.__listbox.SetSelection(self.value)


# noinspection PyPep8Naming
class ExtComboBox(wx.ComboBox):
    def __init__(self, parent, max_items=-1, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)

        assert max_items > 0 or max_items == -1
        self.max_items = max_items

    def Append(self, new_value):
        if self.FindString(new_value) == wx.NOT_FOUND:
            super().Append(new_value)

            if self.max_items != -1 and self.GetCount() > self.max_items:
                self.SetItems(self.GetStrings()[1:])

    def SetValue(self, new_value):
        index = self.FindString(new_value)

        if index == wx.NOT_FOUND:
            self.Append(new_value)

        self.SetSelection(index)

    def LoadMultiple(self, items_list):
        for item in items_list:
            self.Append(item)


class DoubleStageButton(wx.Button):
    def __init__(self, parent, labels, bitmaps, bitmap_pos=wx.TOP, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)

        assert isinstance(labels, tuple) and isinstance(bitmaps, tuple)
        assert len(labels) == 2
        assert len(bitmaps) in {0, 2}

        self.labels = labels
        self.bitmaps = bitmaps
        self.bitmap_pos = bitmap_pos

        self._stage = 0
        self._set_layout()

    def _set_layout(self):
        self.SetLabel(self.labels[self._stage])

        if len(self.bitmaps):
            self.SetBitmap(self.bitmaps[self._stage], self.bitmap_pos)

    def change_stage(self):
        self._stage = 0 if self._stage else 1
        self._set_layout()

    def set_stage(self, new_stage):
        assert new_stage in [0, 1]

        self._stage = new_stage
        self._set_layout()


class MessageDialog(wx.Dialog):
    STYLE = (
        wx.DEFAULT_DIALOG_STYLE
        if IS_WINDOWS
        else wx.DEFAULT_DIALOG_STYLE | wx.MAXIMIZE_BOX
    )

    def __init__(self, parent, message, title, _dark_mode=False):
        super().__init__(parent, wx.ID_ANY, title, style=self.STYLE)
        self.parent = parent
        self.message = message
        self._dark_mode = _dark_mode

        # Create components
        self.panel = wx.Panel(self)

        self.buttons: dict[str, wx.Button] = {
            "yes": wx.Button(self.panel, wx.ID_YES, _("Yes")),
            "no": wx.Button(self.panel, wx.ID_NO, _("No")),
        }

        info_bmp = wx.ArtProvider.GetBitmap(wx.ART_INFORMATION, wx.ART_MESSAGE_BOX)
        info_icon = wx.StaticBitmap(self.panel, wx.ID_ANY, info_bmp)

        msg_text = wx.StaticText(self.panel, wx.ID_ANY, message)

        # Set sizers
        vertical_sizer = wx.BoxSizer(wx.VERTICAL)

        message_sizer = wx.BoxSizer(wx.HORIZONTAL)
        message_sizer.Add(info_icon)
        message_sizer.AddSpacer(10)
        message_sizer.Add(msg_text, flag=wx.EXPAND | wx.TOP | wx.BOTTOM, border=5)

        vertical_sizer.Add(message_sizer, 1, wx.ALL, border=10)

        buttons_sizer = wx.StdDialogButtonSizer()

        for button in self.buttons.values():
            button.Bind(wx.EVT_BUTTON, self._on_close)
            buttons_sizer.AddButton(button)

        self.buttons["no"].SetDefault()

        buttons_sizer.Realize()

        vertical_sizer.Add(buttons_sizer, flag=wx.EXPAND | wx.ALL, border=10)

        self.panel.SetSizer(vertical_sizer)

        width, height = self.panel.GetBestSize()
        self.SetSize((width, int(height * 1.8)))

        # Set Dark Theme
        dark_mode(self.panel, self._dark_mode)

        self.Center()

    def _on_close(self, event):
        self.EndModal(event.GetEventObject().GetId())


class ButtonsChoiceDialog(wx.Dialog):

    STYLE = (
        wx.DEFAULT_DIALOG_STYLE
        if IS_WINDOWS
        else wx.DEFAULT_DIALOG_STYLE | wx.MAXIMIZE_BOX
    )

    def __init__(self, parent, choices, message, title, _dark_mode=False):
        super().__init__(parent, wx.ID_ANY, title, style=self.STYLE)
        self._dark_mode = _dark_mode

        self.buttons: dict[str, wx.Button] = {}

        # Create components
        self.panel = wx.Panel(self)

        info_bmp = wx.ArtProvider.GetBitmap(wx.ART_INFORMATION, wx.ART_MESSAGE_BOX)

        info_icon = wx.StaticBitmap(self.panel, wx.ID_ANY, info_bmp)
        msg_text = wx.StaticText(self.panel, wx.ID_ANY, message)

        self.buttons["cancel"] = wx.Button(self.panel, wx.ID_CANCEL, _("Cancel"))

        for index, label in enumerate(choices):
            key: str = str(index + 1)
            self.buttons[key] = wx.Button(self.panel, int(key), label)

        # Get the maximum button width & height
        max_width = max_height = -1

        for button in self.buttons.values():
            button_width, button_height = button.GetSize()

            if button_width > max_width:
                max_width = button_width

            if button_height > max_height:
                max_height = button_height

        max_width += 10

        # Set buttons width & bind events
        for button in self.buttons.values():
            if button != self.buttons["cancel"]:
                button.SetMinSize((max_width, max_height))
            else:
                # On Cancel button change only the height
                button.SetMinSize((-1, max_height))

            button.Bind(wx.EVT_BUTTON, self._on_close)

        # Set sizers
        vertical_sizer = wx.BoxSizer(wx.VERTICAL)

        message_sizer = wx.BoxSizer(wx.HORIZONTAL)
        message_sizer.Add(info_icon)
        message_sizer.AddSpacer(10)
        message_sizer.Add(msg_text, flag=wx.EXPAND | wx.TOP | wx.BOTTOM, border=5)

        vertical_sizer.Add(message_sizer, 1, wx.ALL, border=10)

        buttons_sizer = wx.BoxSizer(wx.HORIZONTAL)

        for button in (self.buttons["1"], self.buttons["2"]):
            buttons_sizer.Add(button)
            buttons_sizer.AddSpacer(5)

        buttons_sizer.AddSpacer(1)
        buttons_sizer.Add(self.buttons["cancel"])
        vertical_sizer.Add(buttons_sizer, flag=wx.EXPAND | wx.ALL, border=10)

        self.panel.SetSizer(vertical_sizer)

        width, height = self.panel.GetBestSize()
        self.SetSize((width, int(height * 1.5)))

        # Set Dark Theme
        dark_mode(self.panel, self._dark_mode)

        self.Center()

    def _on_close(self, event):
        self.EndModal(event.GetEventObject().GetId())


class ClipDialog(wx.Dialog):

    FRAME_SIZE = (195, 170) if IS_WINDOWS else (350, 250)

    CHECK_OPTIONS = ("--external-downloader", "--external-downloader-args")

    def __init__(
        self,
        parent: MainFrame,
        download_item: DownloadItem,
        _dark_mode: bool = False,
    ):
        super().__init__(
            parent, wx.ID_ANY, title=_("Clip Multimedia"), style=wx.DEFAULT_DIALOG_STYLE
        )
        self.download_item = download_item
        clip_start, clip_end = self._get_timespans()

        self._dark_mode = _dark_mode

        # Create components
        self.panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        h_time_box = wx.BoxSizer(wx.HORIZONTAL)

        start_label = wx.StaticText(self.panel, wx.ID_ANY, _("Clip start") + ":")
        h_time_box.Add(start_label, 0, wx.ALIGN_CENTRE | wx.ALL, 5)
        h_time_box.AddStretchSpacer(1)
        self.clip_start = masked.TimeCtrl(
            self.panel, wx.ID_ANY, value=clip_start, fmt24hr=True, name="startTime"
        )
        height = self.clip_start.GetSize().height
        spin1 = wx.SpinButton(
            self.panel, wx.ID_ANY, wx.DefaultPosition, (-1, height), wx.SP_VERTICAL
        )
        self.clip_start.BindSpinButton(spin1)
        hbox1 = wx.BoxSizer(wx.HORIZONTAL)
        hbox1.Add(self.clip_start, 0, wx.ALIGN_CENTRE)
        hbox1.Add(spin1, 0, wx.ALIGN_CENTRE)

        h_time_box.Add(hbox1, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(h_time_box, 0, wx.EXPAND | wx.ALL, 5)

        h_time_box = wx.BoxSizer(wx.HORIZONTAL)

        end_label = wx.StaticText(self.panel, wx.ID_ANY, _("Clip end") + ":")
        h_time_box.Add(end_label, 0, wx.ALIGN_CENTRE | wx.ALL, 5)
        h_time_box.AddStretchSpacer(1)
        spin2 = wx.SpinButton(
            self.panel, wx.ID_ANY, wx.DefaultPosition, (-1, height), wx.SP_VERTICAL
        )
        self.clip_end = masked.TimeCtrl(
            self.panel,
            wx.ID_ANY,
            value=clip_end,
            fmt24hr=True,
            name="endTime",
            spinButton=spin2,
        )
        hbox2 = wx.BoxSizer(wx.HORIZONTAL)
        hbox2.Add(self.clip_end, 0, wx.ALIGN_CENTRE)
        hbox2.Add(spin2, 0, wx.ALIGN_CENTRE)

        h_time_box.Add(hbox2, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(h_time_box, 0, wx.EXPAND | wx.ALL, 5)

        line = wx.StaticLine(
            self.panel, wx.ID_ANY, size=(-1, -1), style=wx.LI_HORIZONTAL
        )
        sizer.Add(line, 0, wx.EXPAND | wx.TOP, 5)

        buttons_sizer = wx.StdDialogButtonSizer()

        btn = wx.Button(self.panel, wx.ID_OK)
        btn.Bind(wx.EVT_BUTTON, self._on_close)
        btn.SetDefault()

        buttons_sizer.AddButton(btn)

        btn = wx.Button(self.panel, wx.ID_CANCEL)
        buttons_sizer.AddButton(btn)
        buttons_sizer.Realize()

        sizer.Add(buttons_sizer, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.ALL, 5)

        self.panel.SetSizer(sizer)
        # Set Dark Theme
        dark_mode(self.panel, self._dark_mode)

        self.SetSize(self.FRAME_SIZE)
        self.Center()
        # TODO: Make better decision
        self._clean_options()

    def _clean_options(self):
        """
        Clean the CHECK_OPTIONS from self.download_item.options

        """
        options = []

        for idx, opt in enumerate(self.download_item.options):
            if opt in self.CHECK_OPTIONS:
                with contextlib.suppress(IndexError):
                    opt_arg = self.download_item.options[idx + 1]
                    if opt_arg == "ffmpeg" or "-ss" in opt_arg or "-to" in opt_arg:
                        self.download_item.options.pop(idx + 1)
                continue

            options.append(opt)

        if options:
            self.download_item.options = options

    def _get_timespans(self) -> tuple[str, str]:
        """
        Get the TimeSpan if CHECK_OPTIONS[1] in self.download_item.options

        Returns:
            Tuple of strings with the clip_start and clip_end in format HH:MM:SS

        """
        external_downloader_args: str | None = None
        downloader_args: list[str] | None = None
        clip_start = clip_end = index = 0

        for idx, option in enumerate(self.download_item.options):
            if self.CHECK_OPTIONS[1] == option:
                try:
                    external_downloader_args = self.download_item.options[idx + 1]
                    index = idx
                except IndexError:
                    # No exist timespans
                    self.download_item.options.pop(idx)
                break

        if external_downloader_args:
            downloader_args = external_downloader_args.split()

        if downloader_args and len(downloader_args) == 4:
            # Clean quotes (simple/double)
            try:
                clip_start = int(downloader_args[1].strip("'\""))
                clip_end = int(downloader_args[-1].strip("'\""))
            except ValueError:
                self.download_item.options.pop(index + 1)
                self.download_item.options.pop(index)

        wx_clip_start = str(timedelta(seconds=clip_start))
        wx_clip_end = str(timedelta(seconds=clip_end))
        return wx_clip_start, wx_clip_end

    def _on_close(self, event):
        _clip_start = int(self.clip_start.GetValue(as_wxTimeSpan=True).GetSeconds())
        _clip_end = int(self.clip_end.GetValue(as_wxTimeSpan=True).GetSeconds())

        if _clip_start > _clip_end or _clip_start == _clip_end:
            wx.MessageBox(
                _("Invalid timespan"), _("Warning"), wx.OK | wx.ICON_EXCLAMATION
            )
            return

        self.EndModal(event.GetEventObject().GetId())


class ShutdownDialog(wx.Dialog):
    STYLE = (
        wx.DEFAULT_DIALOG_STYLE
        if IS_WINDOWS
        else wx.DEFAULT_DIALOG_STYLE | wx.MAXIMIZE_BOX
    )

    TIMER_INTERVAL = 1000  # milliseconds

    def __init__(self, parent, timeout, message, *args, **kwargs):
        super().__init__(parent, wx.ID_ANY, *args, style=self.STYLE, **kwargs)
        assert timeout > 0

        self.timeout = timeout
        self.message = message

        # Create components
        panel = wx.Panel(self)

        info_bmp = wx.ArtProvider.GetBitmap(wx.ART_INFORMATION, wx.ART_MESSAGE_BOX)
        info_icon = wx.StaticBitmap(panel, wx.ID_ANY, info_bmp)

        self.msg_text = msg_text = wx.StaticText(panel, wx.ID_ANY, self._get_message())
        ok_button = wx.Button(panel, wx.ID_OK, _("OK"))
        cancel_button = wx.Button(panel, wx.ID_CANCEL, _("Cancel"))

        # Set layout
        vertical_sizer = wx.BoxSizer(wx.VERTICAL)

        message_sizer = wx.BoxSizer(wx.HORIZONTAL)
        message_sizer.Add(info_icon)
        message_sizer.AddSpacer((10, 10))
        message_sizer.Add(msg_text, flag=wx.EXPAND)

        vertical_sizer.Add(message_sizer, 1, wx.ALL, border=10)

        buttons_sizer = wx.BoxSizer(wx.HORIZONTAL)
        buttons_sizer.Add(ok_button)
        buttons_sizer.AddSpacer((5, -1))
        buttons_sizer.Add(cancel_button)

        vertical_sizer.Add(buttons_sizer, flag=wx.ALIGN_RIGHT | wx.ALL, border=10)

        panel.SetSizer(vertical_sizer)

        width, height = panel.GetBestSize()
        self.SetSize((width * 1.3, height * 1.3))

        self.Center()

        # Set up timer
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_timer, self.timer)
        self.timer.Start(self.TIMER_INTERVAL)

    def _get_message(self):
        return self.message.format(self.timeout)

    # noinspection PyUnusedLocal
    def _on_timer(self, event):
        self.timeout -= 1
        self.msg_text.SetLabel(self._get_message())

        if self.timeout <= 0:
            self.EndModal(wx.ID_OK)

    def Destroy(self):
        self.timer.Stop()
        return super().Destroy()


# noinspection PyUnresolvedReferences
class LogGUI(wx.Frame):
    """Simple window for reading the STDERR.

    Attributes:
        FRAME_SIZE (tuple): Tuple that holds the frame size (width, height).

    Args:
        parent (MainFrame): Frame parent.

    """

    FRAME_SIZE: tuple[int, int] = (750, 200)

    def __init__(self, parent: MainFrame | OptionsFrame | None = None):
        super().__init__(parent, title=_("Log Viewer"), size=self.FRAME_SIZE)
        self.parent = parent
        self.app_icon: wx.Icon | None = self.parent.app_icon

        if self.app_icon:
            self.SetIcon(self.app_icon)

        self.panel = wx.Panel(self)

        self._text_area = wx.TextCtrl(
            self.panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL
        )

        sizer = wx.BoxSizer()
        sizer.Add(self._text_area, 1, wx.EXPAND)
        self.panel.SetSizerAndFit(sizer)

    def load(self, filename: str):
        """Load file content on the text area."""
        if Path(filename).exists():
            self._text_area.LoadFile(filename)
