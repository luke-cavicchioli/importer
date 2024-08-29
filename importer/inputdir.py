"""Choose input directories."""

import logging
import os
import warnings
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import List, Optional, Union

import questionary

from importer.statuscb import StatusCB

logger = logging.getLogger("importer.inputdir")


class InputSt(Enum):
    """Which input strategy is needed."""

    TODAY = auto()
    DATE = auto()
    PATH = auto()
    INTERACTIVE = auto()


class InputDIR:
    """Represent the input directory, as chosen by the user.

    :param today: If True, search the directory with the modified date closest
        to today's. Highest priority, overrides both date and inpath.
    :param date: If not None, search the directory with the closest date to the
        given value. Overrides inpath.
    :param inpath: If not None, get the directory with the specified path.
    :param search_cb: StatusCB instance to be called before and after the search.
    """

    def __init__(
            self,
            today: bool,
            date: Optional[datetime],
            inpath: Optional[Path],
            root: Optional[Path],
            search_cb: StatusCB = StatusCB()
    ):
        """Initialize the instance."""
        self._today = today
        self._date = date
        self._inpath = inpath
        self._root = root
        self._search_cb = search_cb
        self._strategy = self._choose_strategy()

    def _choose_strategy(self):
        """Choose an input strategy, according to override rules."""
        if self._today:
            if self._date is not None:
                warnings.warn("Today input will override date.")
            if self._inpath is not None:
                warnings.warn("Today input will override path.")
            return InputSt.TODAY
        elif self._date is not None:
            if self._inpath is not None:
                warnings.warn("Date input will override path.")
            return InputSt.DATE
        elif self._inpath is not None:
            return InputSt.PATH
        else:
            return InputSt.INTERACTIVE

    def _get_today_dir(self) -> Optional[Path]:
        """Get the directory with the modification date closest to today.

        :return: An (optional) path representing the selected directory.
        """
        date = datetime.now()
        return date_dir(date=date, root=self._root, scb=self._search_cb)

    def _get_date_dir(self) -> Optional[Path]:
        """Get directory with modification date closest to required date.

        :return: An (optional) path representing the selected directory.
        """
        return date_dir(date=self._date, root=self._root, scb=self._search_cb)

    def _get_path_dir(self) -> Optional[Path]:
        """Get the directory with the inputh path.

        :return: An (optional) path representing the selected directory.
        """
        path = self._inpath
        if self._root is not None and not path.is_absolute():
            path = self._root.joinpath(path)
        return path.resolve()

    def _get_interactive_dir(self) -> Optional[Path]:
        """Interactively get the input path.

        :return: An (optional) path representing the selected directory.
        """
        return dir_input(self._root)

    @property
    def path(self) -> Optional[Path]:
        """The input directory path.

        :return: An (optional) path representing the selected directory.
        """
        match self._strategy:
            case InputSt.TODAY:
                return self._get_today_dir()
            case InputSt.DATE:
                return self._get_date_dir()
            case InputSt.PATH:
                return self._get_path_dir()
            case InputSt.INTERACTIVE:
                return self._get_interactive_dir()

    def __repr__(self) -> str:
        """Representation for debugging."""
        return (
            f"InputDIR(today = {self._today}, "
            f"date = {self._date}, "
            f"inpath = {self._inpath}, "
            f"root = {self._root}, "
            f"strategy = {self._strategy})"
        )


def date_dir(date: datetime, root: Optional[Path], scb: StatusCB) -> Optional[Path]:
    """Get directory with modification date closest to required.

    :param date: The required date.
    :param root: The root under which the directory is to be searched. If None,
        search under "./".
    :param scb: A StatusCB to start and stop the status during the search.
    :return: An (optional) path representing the selected directory.
    """
    if root is None:
        root = Path("./").resolve()
    scb.start()
    found = find_date_dir(date, root)
    scb.stop()
    return dir_selector(found)


def find_date_dir(date: datetime, root: Path, n: int = 10) -> List[Path]:
    """Find best matching directories in the root path.

    :param date: The required date.
    :param root: The root under which the directory should be searched.
    :param n: The number of matches, defaults to 10.
    :return: The list of the best matching directories.
    """
    found = []

    for curr, subdns, _ in os.walk(root):
        # append current directory if none visited
        if len(found) == 0:
            found.append((curr, Path(curr), datescore_dir(curr, date)))

        # find scores for all sub-directories
        subdps = [(d, Path(curr).joinpath(d).resolve())
                  for d in subdns]
        subdss = [(d, p, datescore_dir(p, date)) for d, p in subdps]

        # keep only subdss members that would be in top ten
        subdss.sort(key=lambda x: x[2])
        found[:] = found + subdss
        found.sort(key=lambda x: x[2])
        found[:] = found[:min(len(found), n)]
        max_found = found[-1][2]
        subdss = [(d, s) for d, _, s in subdss if s <= max_found]

        # traverse only subdirectories in subdss (i.e. directories in top ten)
        subdns[:] = [d for d, _ in subdss]

    found = [x[1] for x in found]
    return found


def datescore_dir(dir: Path, target: datetime) -> int:
    """Score directory according to distance from date.

    :param dir: The directory to be scored.
    :param target: The target date.
    :return: The distance of the modification date of the directory from the
        target date (in seconds).
    """
    mtime = datetime.fromtimestamp(os.stat(dir).st_mtime)
    delta = mtime - target
    return abs(int(delta.total_seconds()))


def dir_selector(found: List[Path]) -> Optional[Path]:
    """Choose interactively a directory from a list.

    :param found: List of matching directories.
    :return: A Path to the input directory, or None if the user cancels (with
        C-c).
    """
    foundstr = [str(x) for x in found]
    ans = questionary.select(
        "Best matches:",
        instruction="Enter to select the desired directory, C-c to cancel",
        choices=foundstr,
        show_selected=True
    ).ask()
    logger.debug(f"{ans = }")
    return Path(ans) if ans is not None else None


def dir_input(root: Optional[Path]) -> Optional[Path]:
    """Interactively get the input path.

    :param root: The root under which the input path should be chosen. If None,
        seeks under "./"
    :return: The path of the chosen input directory, or None if user cancels.
    """
    if root is None:
        root = Path(".")
    logger.debug(f"{root = }")

    def validate_dir(dir: str) -> Union[bool, str]:
        """Directory validation for questionary."""
        if os.path.isdir(dir):
            return True
        else:
            return "Not a directory"

    ans = questionary.path(
        message="Choose input path: ",
        default=str(root),
        only_directories=True,
        validate=validate_dir
    ).ask()
    logger.debug(f"{ans = }")

    return Path(ans) if ans is not None else None
