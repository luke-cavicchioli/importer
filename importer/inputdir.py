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
    TODAY = auto()
    DATE = auto()
    PATH = auto()
    INTERACTIVE = auto()


class InputDIR:
    def __init__(
            self,
            today: bool,
            date: Optional[datetime],
            inpath: Optional[Path],
            root: Optional[Path],
            search_cb: StatusCB = StatusCB()
    ):
        self._today = today
        self._date = date
        self._inpath = inpath
        self._root = root
        self._search_cb = search_cb
        self._strategy = self._choose_strategy()

    def _choose_strategy(self):
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
        date = datetime.now()
        return date_dir(date=date, root=self._root, scb=self._search_cb)

    def _get_date_dir(self) -> Optional[Path]:
        return date_dir(date=self._date, root=self._root, scb=self._search_cb)

    def _get_path_dir(self) -> Optional[Path]:
        path = self._inpath
        if self._root is not None and not path.is_absolute():
            path = self._root.joinpath(path)
        return path.resolve()

    def _get_interactive_dir(self) -> Optional[Path]:
        return dir_input(self._root)

    @property
    def path(self):
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
        return (
            f"InputDIR(today = {self._today}, "
            f"date = {self._date}, "
            f"inpath = {self._inpath}, "
            f"root = {self._root}, "
            f"strategy = {self._strategy})"
        )


def date_dir(date: datetime, root: Optional[Path], scb: StatusCB) -> Optional[Path]:
    if root is None:
        root = Path("./").resolve()
    scb.start()
    found = find_date_dir(date, root)
    scb.stop()
    return dir_selector(found)


def find_date_dir(date: datetime, root: Path, n: int = 10):
    """Find best matching directories in the root path."""
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

    found = [str(x[1]) for x in found]
    return found


def datescore_dir(dir: Path, target: datetime) -> int:
    """Score directory according to distance from date."""
    mtime = datetime.fromtimestamp(os.stat(dir).st_mtime)
    delta = mtime - target
    return abs(int(delta.total_seconds()))


def dir_selector(found: List[Path]) -> Optional[Path]:
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
    """Interactively get the input path."""
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
