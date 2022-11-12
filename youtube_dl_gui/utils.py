# type: ignore[misc]
"""yt-dlg module that contains util functions.

Attributes:

    YOUTUBEDL_BIN (string): Youtube-dl binary filename.

"""
from __future__ import annotations

import locale
import math
import os
import subprocess
import sys
from pathlib import Path

from .info import __appname__

IS_WINDOWS = os.name == "nt"

YOUTUBEDL_BIN: str = "youtube-dl"
if IS_WINDOWS:
    YOUTUBEDL_BIN += ".exe"

YTDLP_BIN: str = "yt-dlp"
if IS_WINDOWS:
    YTDLP_BIN += ".exe"

FILESIZE_METRICS = ["B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB"]

KILO_SIZE = 1024.0

locale_getdefaultlocale = locale.getdefaultlocale

locale_getpreferredencoding = locale.getpreferredencoding


def get_encoding() -> str:
    """Return system encoding, elsese utf-8"""
    try:
        encoding = locale_getpreferredencoding()
        _ = "TEST".encode(encoding)
    except locale.Error:
        encoding = "utf-8"

    return encoding


def startfile(file_path: str) -> None:
    if os.name == "nt":
        os.startfile(file_path)
    else:
        subprocess.call(("xdg-open", file_path))


os_startfile = startfile


def remove_file(filename: str) -> bool:
    file_path = Path(filename)
    if file_path.exists():
        file_path.unlink()
        return True

    return False


def remove_shortcuts(path: str) -> str:
    """Return given path after removing the shortcuts."""
    return path.replace("~", str(Path().home()))


def absolute_path(filename: str) -> str:
    """Return absolute path to the given file."""
    return str(Path(filename).resolve())


def open_file(file_path: str) -> bool:
    """Open file in file_path using the default OS application.

    Returns:
        True on success else False.

    """

    if not Path(file_path).exists():
        return False

    os_startfile(file_path)

    return True


def encode_tuple(tuple_to_encode: tuple[int, int]) -> str:
    """Turn size tuple into string."""
    return f"{tuple_to_encode[0]}/{tuple_to_encode[1]}"


def decode_tuple(encoded_tuple: str) -> tuple[int, int]:
    """Turn tuple string back to tuple."""
    s = encoded_tuple.split("/")
    return int(s[0]), int(s[1])


def check_path(path: str) -> None:
    """Create path if not exist."""
    if not Path(path).exists():
        os.makedirs(path)


# noinspection PyUnusedLocal
def get_config_path() -> str:
    """Return user config path.

    Note:
        Windows = %AppData% + app_name
        Linux   = ~/.config + app_name

    """
    ytdlg_path: str = ""

    if os.name == "nt":
        ytdlg_path = os.getenv("APPDATA", "")
    else:
        ytdlg_path = str(Path().home() / Path(".config"))

    return str(Path(ytdlg_path) / Path(__appname__.lower()))


# noinspection PyUnusedLocal
def shutdown_sys(password=None) -> bool:
    """Shuts down the system.
    Returns True if no errors occur else False.

    Args:
        password (string): SUDO password for linux.

    Note:
        On Linux you need to provide sudo password if you don't
        have elevated privileges.

    """
    info = None
    cmd = []
    encoding: str = get_encoding()

    kwargs = dict(
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        encoding=encoding,
        creationflags=0,
    )

    if os.name == "nt":
        cmd = ["shutdown", "/s", "/t", "1"]

        # Hide subprocess window
        info = subprocess.STARTUPINFO()
        info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        info.wShowWindow = subprocess.SW_HIDE

        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

        if password:
            password = "%s\n" % password
            cmd = ["sudo", "-S", "/sbin/shutdown", "-h", "now"]
        else:
            cmd = ["/sbin/shutdown", "-h", "now"]

    shutdown_proc = subprocess.Popen(
        cmd, startupinfo=info, **kwargs
    )  # type: ignore[call-overload]

    output = shutdown_proc.communicate(password)[1]

    return not output or output == "Password:"


def get_time(seconds: float) -> dict[str, int]:
    """Convert given seconds to days, hours, minutes and seconds.

    Args:
        seconds (float): Time in seconds.

    Returns:
        Dictionary that contains the corresponding days, hours, minutes
        and seconds of the given seconds.

    """
    dtime = dict(seconds=0, minutes=0, hours=0, days=0)

    dtime["days"] = int(seconds / 86400)
    dtime["hours"] = int(seconds % 86400 / 3600)
    dtime["minutes"] = int(seconds % 86400 % 3600 / 60)
    dtime["seconds"] = int(seconds % 86400 % 3600 % 60)

    return dtime


def get_search_dirs(dir_name: str) -> list[Path]:
    return [
        Path(sys.argv[0]) / Path(dir_name),
        Path(__file__).parent / Path(dir_name),
    ]


# noinspection PyPep8Naming
def get_locale_file() -> str | None:
    """Search for yt_dlg locale file.

    Returns:
        The path to yt_dlg locale file if exists else None.

    Note:
        Paths that get_locale_file() func searches.

        __main__ dir, library dir

    """
    SEARCH_DIRS = get_search_dirs("locale")

    return next(
        (str(directory) for directory in SEARCH_DIRS if directory.is_dir()), None
    )


# noinspection PyPep8Naming
def get_icon_file() -> str | None:
    """Search for yt_dlg app icon.

    Returns:
        The path to yt_dlg icon file if exists, else returns None.

    """
    pixmaps_dir = get_pixmaps_dir()

    if pixmaps_dir:
        ICON_NAME = "youtube-dl-gui.png"

        icon_file = Path(pixmaps_dir) / Path(ICON_NAME)

        if icon_file.exists():
            return str(icon_file)

    return None


# noinspection PyPep8Naming
def get_pixmaps_dir() -> str | None:
    """Return absolute path to the pixmaps icons folder.

    Note:
        Paths we search: __main__ dir, library dir

    """
    SEARCH_DIRS = get_search_dirs("data")

    for directory in SEARCH_DIRS:
        pixmaps_dir = directory / Path("pixmaps")

        if pixmaps_dir.is_dir():
            return str(pixmaps_dir)

    return None


def to_bytes(string: str) -> float:
    """Convert given youtube-dl size string to bytes."""
    value = 0.0
    index = 0

    for index, metric in enumerate(reversed(FILESIZE_METRICS)):
        if metric in string:
            value = float(string.split(metric)[0])
            break

    exponent = index * (-1) + (len(FILESIZE_METRICS) - 1)

    return round(value * (KILO_SIZE**exponent), 2)


def format_bytes(bytes_: float) -> str:
    """Format bytes to youtube-dl size output strings."""
    exponent = 0 if bytes_ == 0.0 else int(math.log(bytes_, KILO_SIZE))
    suffix = FILESIZE_METRICS[exponent]
    output_value = bytes_ / (KILO_SIZE**exponent)

    return f"{output_value:.2f}{suffix}"


def build_command(
    options_list: list[str], url: str, cli_backend: str = YOUTUBEDL_BIN
) -> str:
    """Build the CLI Backend command line string."""

    def escape(option: str) -> str:
        """Wrap option with double quotes if it contains special symbols."""

        special_symbols: list[str] = [" ", "(", ")"]

        for symbol in special_symbols:
            if symbol in option:
                return f'"{option}"'

        return option

    # If option has special symbols wrap it with double quotes
    # Probably not the best solution since if the option already contains
    # double quotes it will be a mess, see issue #173
    options: list[str] = [escape(option) for option in options_list]

    # Always wrap the url with double quotes
    url = f'"{url}"'

    return " ".join([cli_backend] + options + [url])


def get_default_lang() -> str:
    """Get default language using the 'locale' module."""
    default_lang, _ = locale_getdefaultlocale()

    return default_lang or "en_US"


def get_key(string: str, dictionary: dict[str, str], default: str = "") -> str:
    """Get key from a value in Dictionary. Return default if key doesn't exist"""
    return next((key for key, value in dictionary.items() if value == string), default)
