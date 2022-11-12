# type: ignore[misc]
"""yt-dlg module responsible for parsing the options. """
from __future__ import annotations

from pathlib import Path
from typing import Any

from .utils import remove_shortcuts


class OptionHolder:
    """Simple data structure that holds informations for the given option.

    Args:
        name (str): Option name. Must be a valid option name
            from the optionsmanager.OptionsManager class.
            See optionsmanager.OptionsManager load_default() method.

        flag (str): The option command line switch.
            See https://github.com/ytdl-org/youtube-dl/#options

        default_value (Any): The option default value. Must be the same type
            with the corresponding option from the optionsmanager.OptionsManager
            class.

        requirements (list): The requirements for the given option. This
            argument is a list of strings with the name of all the options
            that this specific option needs. For example 'subs_lang' needs the
            'write_subs' option to be enabled.

    """

    def __init__(
        self,
        name: str,
        flag: str,
        default_value: str | int | bool,
        requirements: list[str] | None = None,
    ):
        self.name = name
        self.flag = flag
        self.default_value = default_value
        self.requirements = requirements

    def is_boolean(self) -> bool:
        """Returns True if the option is a boolean switch else False."""
        return type(self.default_value) is bool

    def check_requirements(self, options_dict: dict[str, Any]) -> bool:
        """Check if the required options are enabled.

        Args:
            options_dict (dict): Dictionary with all the options.

        Returns:
            True if any of the required options is enabled else False.

        """
        if self.requirements is None:
            return True

        return any(options_dict[req] for req in self.requirements)


class OptionsParser:
    """Parse optionsmanager.OptionsManager options.

    This class is responsible for turning some of the youtube-dlg options
    to youtube-dl command line options.

    """

    def __init__(self):
        self._ydl_options = [
            OptionHolder("playlist_start", "--playlist-start", 1),
            OptionHolder("playlist_end", "--playlist-end", 0),
            OptionHolder("max_downloads", "--max-downloads", 0),
            OptionHolder("username", "-u", ""),
            OptionHolder("password", "-p", ""),
            OptionHolder("video_password", "--video-password", ""),
            OptionHolder("retries", "-R", 10),
            OptionHolder("proxy", "--proxy", ""),
            OptionHolder("user_agent", "--user-agent", ""),
            OptionHolder("referer", "--referer", ""),
            OptionHolder("ignore_errors", "-i", False),
            OptionHolder("write_description", "--write-description", False),
            OptionHolder("write_info", "--write-info-json", False),
            OptionHolder("write_thumbnail", "--write-thumbnail", False),
            OptionHolder("min_filesize", "--min-filesize", 0),
            OptionHolder("max_filesize", "--max-filesize", 0),
            OptionHolder("write_all_subs", "--all-subs", False),
            OptionHolder("write_auto_subs", "--write-auto-sub", False),
            OptionHolder("write_subs", "--write-sub", False),
            OptionHolder("keep_video", "-k", False),
            OptionHolder("restrict_filenames", "--restrict-filenames", False),
            OptionHolder("save_path", "-o", ""),
            OptionHolder(
                "embed_subs", "--embed-subs", False, ["write_auto_subs", "write_subs"]
            ),
            OptionHolder("to_audio", "-x", False),
            OptionHolder("audio_format", "--audio-format", ""),
            OptionHolder("video_format", "-f", "0"),
            OptionHolder("subs_lang", "--sub-lang", "", ["write_subs"]),
            OptionHolder("audio_quality", "--audio-quality", "5", ["to_audio"]),
            OptionHolder("youtube_dl_debug", "-v", False),
            OptionHolder("ignore_config", "--ignore-config", False),
            OptionHolder("native_hls", "--hls-prefer-native", False),
            OptionHolder("nomtime", "--no-mtime", False),
            OptionHolder("embed_thumbnail", "--embed-thumbnail", False),
            OptionHolder("add_metadata", "--add-metadata", False),
        ]

    def parse(self, options_dictionary: dict[str, Any]) -> list[str]:
        """Parse optionsmanager.OptionsManager options.

        Parses the given options to youtube-dl command line arguments.

        Args:
            options_dictionary (dict): Dictionary with all the options.

        Returns:
            List of strings with all the youtube-dl command line options.

        """
        options_list: list[str] = ["--newline"]

        # Create a copy of options_dictionary
        # We don't want to edit the original options dictionary
        # and change some of the options values like 'save_path' etc..
        options_dict = options_dictionary.copy()

        self._build_savepath(options_dict)
        self._build_videoformat(options_dict)
        self._build_filesizes(options_dict)

        # Parse basic youtube-dl command line options
        for option in self._ydl_options:
            # NOTE Special case should be removed
            if option.name == "to_audio" and not options_dict["audio_format"]:
                value = options_dict[option.name]

                if value != option.default_value:
                    options_list.append(option.flag)
            elif option.name == "audio_format":
                value = options_dict[option.name]

                if value != option.default_value:
                    if "-x" not in options_list:
                        options_list.append("-x")
                    options_list.extend((option.flag, str(value)))
                    # NOTE Temp fix
                    # If current 'audio_quality' is not the default one ('5')
                    # then append the audio quality flag and value to the
                    # options list
                    if options_dict["audio_quality"] != "5":
                        options_list.extend(
                            ("--audio-quality", str(options_dict["audio_quality"]))
                        )
            elif option.name == "audio_quality":
                # If the '--audio-quality' is not already in the options list
                # from the above branch then follow the standard procedure.
                # We don't have to worry for the sequence in which the code
                # will be executed since the 'audio_quality' option is placed
                # after the 'audio_format' option in the self._ydl_options list
                if option.flag not in options_list and option.check_requirements(
                    options_dict
                ):
                    value = options_dict[option.name]
                    assert 0 <= int(value) <= 9

                    options_list.extend((option.flag, str(value)))
            elif option.check_requirements(options_dict):
                value = options_dict[option.name]

                if value != option.default_value:
                    options_list.append(option.flag)

                    if not option.is_boolean():
                        options_list.append(str(value))

        self.parse_cmd_args(options_dict, options_list)

        return options_list

    @staticmethod
    def parse_cmd_args(options_dict: dict[str, Any], options_list: list[str]) -> None:
        """
        Parse cmd_args

        Args:
            options_dict (dict): Reference to options dictionary.
            options_list (list): Reference to options list to parse.

        """
        # TODO: Handle special cases of single and doble queotes in options better

        # Indicates whether an item needs special handling
        special_case = False

        # Temp list to hold special items
        special_items = []

        for item in options_dict["cmd_args"].split():

            # Its a special case if its already a special case
            # or an item starts with single/double quotes
            special_case = special_case or item[0] in ['"', "'"]

            if special_case:
                special_items.append(item)
            else:
                options_list.append(item)

            # If its a special case and we meet a double quote
            # at the end of the item, special case is over and
            # we need to join, filter and append our special items
            # to the options list
            if special_case and item[-1] in ['"', "'"]:
                options_list.append(" ".join(special_items)[1:-1])

                special_case = False
                special_items = []

    @staticmethod
    def _build_savepath(options_dict: dict[str, str]) -> None:
        """Build the save path.

        We use this method to build the value of the 'save_path' option and
        store it back to the options dictionary.

        Args:
            options_dict (dict): Copy of the original options dictionary.

        """
        # Check OUTPUT_FORMATS values (str)
        assert isinstance(options_dict["output_format"], str)

        save_path: str = remove_shortcuts(options_dict["save_path"])

        if options_dict["output_format"] == "0":
            template: str = "%(id)s.%(ext)s"
        elif options_dict["output_format"] == "1":
            template = "%(title)s.%(ext)s"
        elif options_dict["output_format"] == "2":
            template = "%(title)s-%(id)s.%(ext)s"
        elif options_dict["output_format"] == "4":
            template = "%(title)s-%(height)sp.%(ext)s"
        elif options_dict["output_format"] == "5":
            template = "%(title)s-%(id)s-%(height)sp.%(ext)s"
        else:
            template = options_dict["output_template"]

        options_dict["save_path"] = str(Path(save_path) / Path(template))

    @staticmethod
    def _build_videoformat(options_dict: dict[str, str]) -> None:
        """Build the video format.

        We use this method to build the value of the 'video_format' option and
        store it back to the options dictionary.

        Args:
            options_dict (dict): Copy of the original options dictionary.

        """
        if (
            options_dict["video_format"] != "0"
            and options_dict["second_video_format"] != "0"
        ):
            options_dict[
                "video_format"
            ] = f'{options_dict["video_format"]}+{options_dict["second_video_format"]}'

    @staticmethod
    def _build_filesizes(options_dict: dict[str, str | int]) -> None:
        """Build the filesize options values.

        We use this method to build the values of 'min_filesize' and
        'max_filesize' options and store them back to options dictionary.

        Args:
            options_dict (dict): Copy of the original options dictionary.

        """
        min_filesize = options_dict.get("min_filesize")
        max_filesize = options_dict.get("max_filesize")

        if min_filesize:
            options_dict[
                "min_filesize"
            ] = f'{options_dict["min_filesize"]}{options_dict["min_filesize_unit"]}'

        if max_filesize:
            options_dict[
                "max_filesize"
            ] = f'{options_dict["max_filesize"]}{options_dict["max_filesize_unit"]}'
