"""yt-dlg wx Application

Example:
    In order to load the GUI from a python script.

        from youtube_dl_gui import app

        app.main()

"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

import wx

from .info import __appname__, __packagename__
from .logmanager import LogManager
from .mainframe import MainFrame
from .optionsmanager import OptionsManager
from .utils import YOUTUBEDL_BIN, get_config_path, get_locale_file
from .version import __version__

_: Callable[[str], str] = wx.GetTranslation

# Set config path and create options and log managers
config_path: str = get_config_path()

opt_manager = OptionsManager(config_path)
log_manager = None

if opt_manager.options.get("enable_log", True):
    log_manager = LogManager(config_path, opt_manager.options.get("log_time", True))

locale_dir: str = get_locale_file() or "."


# noinspection PyPep8Naming
def _displayHook(obj: Any) -> None:
    """
    Install a custom displayhook to keep Python from setting the global
    _ (underscore) to the value of the last evaluated expression.  If
    we don't do this, our mapping of _ to gettext can get overwritten.
    This is useful/needed in interactive debugging with PyShell.

    :param Any `obj`: object to string representation

    """
    if obj is not None:
        print(repr(obj))


# noinspection PyPep8Naming,PyAttributeOutsideInit
class BaseApp(wx.App):
    """Base wx Application"""

    def OnInit(self) -> bool:
        super().OnInit()
        sys.displayhook = _displayHook

        self.appName: str = __appname__
        self.locale: wx.Locale | None = None
        wx.Locale.AddCatalogLookupPathPrefix(locale_dir)
        self.updateLanguage(opt_manager.options.get("locale_name", "en_US"))

        return True

    def updateLanguage(self, lang: str) -> None:
        """
        Update the language to the requested one.

        Make *sure* any existing locale is deleted before the new
        one is created.  The old C++ object needs to be deleted
        before the new one is created, and if we just assign a new
        instance to the old Python variable, the old C++ locale will
        not be destroyed soon enough, likely causing a crash.

        Args:
             lang (str): one of the supported language codes

        """

        # Supported Languages
        # Lang code = <ISO 639-1>_<ISO 3166-1 alpha-2>
        supLang: dict[str, int] = {
            "ar_SA": wx.LANGUAGE_ARABIC,
            "cs_CZ": wx.LANGUAGE_CZECH,
            "de_DE": wx.LANGUAGE_GERMAN,
            "en_US": wx.LANGUAGE_ENGLISH_US,
            "fr_FR": wx.LANGUAGE_FRENCH,
            "es_CU": wx.LANGUAGE_SPANISH,
            "it_IT": wx.LANGUAGE_ITALIAN,
            "ja_JP": wx.LANGUAGE_JAPANESE,
            "ko_KR": wx.LANGUAGE_KOREAN,
            "pl_PL": wx.LANGUAGE_POLISH,
            "pt_BR": wx.LANGUAGE_PORTUGUESE_BRAZILIAN,
            "ru_RU": wx.LANGUAGE_RUSSIAN,
            "es_ES": wx.LANGUAGE_SPANISH,
            "sq_AL": wx.LANGUAGE_ALBANIAN,
            "sk_SK": wx.LANGUAGE_SLOVAK,
            "zh_CN": wx.LANGUAGE_CHINESE_SIMPLIFIED,
            "zh_TW": wx.LANGUAGE_CHINESE_TRADITIONAL,
            "tr_TR": wx.LANGUAGE_TURKISH,
        }

        selLang: int = supLang.get(lang, wx.LANGUAGE_ENGLISH)

        if self.locale:
            assert sys.getrefcount(self.locale) <= 2
            del self.locale

        # create a locale object for this language
        if wx.Locale.IsAvailable(selLang):
            self.locale = wx.Locale(selLang)
            if self.locale.IsOk():
                self.locale.AddCatalog(__packagename__)
        else:
            self.locale = None


# BaseApp and MainFrame
app = BaseApp(redirect=False)
frame = MainFrame(opt_manager, log_manager)


def main() -> int:
    """
    The real main. Calls the main app (`BaseApp`) windows.

    Print the version if pass option -v|--version
    """
    _error = 0

    if len(sys.argv) > 1 and sys.argv[1].lower() in ["-v", "--version"]:
        print(f"{__appname__} {__version__}")
        return _error

    youtubedl_path: Path = (
        Path(opt_manager.options.get("youtubedl_path", ".")) / YOUTUBEDL_BIN
    )

    frame.Show()

    if opt_manager.options.get("disable_update", False) and not youtubedl_path.exists():
        wx.MessageBox(
            _("Failed to locate CLI Backend and updates are disabled"),
            _("Error"),
            wx.OK | wx.ICON_ERROR,
        )
        _error = 1
        frame.close()

    app.MainLoop()

    return _error
