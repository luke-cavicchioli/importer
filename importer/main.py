"""Main function of the program."""

import ipaddress
import logging
import os
import pathlib
import shutil
import sys
import tempfile
import warnings
import zipfile
from collections import namedtuple
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Callable, Dict, List, Optional, Union

import click
import questionary
import sh
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import Progress, TaskID
from rich.status import Status
from rich.style import Style

from .inputdir import InputDIR
from .remote import RemoteRepo
from .statuscb import StatusCB

termw = 80

cns = Console(width=termw)

log_handler = RichHandler(
    console=cns,
    show_path=False,
    show_time=False,
)
logger = logging.getLogger("importer")
logger.addHandler(log_handler)
logging.captureWarnings(True)


def formatwarning(message, category, filename, lineno, line=None) -> str:
    """Custom formatting for warnings."""
    return str(message)


warnings.formatwarning = formatwarning
warn_logger = logging.getLogger("py.warnings")
warn_logger.addHandler(log_handler)


CONTEXT_SETTINGS = {
    "terminal_width": termw
}


def main_handle_errors(mainf):
    """Stuff to do before and after the main function."""
    def f(*args, **kwargs):
        cns.rule("IMPORTER")
        ret = mainf(*args, **kwargs)
        cns.rule(
            style=Style(
                color="red" if ret != 0 else "green"
            )
        )
        sys.exit(ret)

    return f


@ click.group(
    help="Import files from a server.",
    invoke_without_command=True,
    context_settings=CONTEXT_SETTINGS,
)
@ click.option(
    "--today",
    "today",
    is_flag=True,
    help="Import from the server a directory with today's date as a name.",
)
@ click.option(
    "-d",
    "--date",
    "datepath",
    default=None,
    type=str,
    help="Import from the server a directory with this date as a name.",
)
@ click.option(
    "-i",
    "--inpath",
    "inpath",
    default=None,
    type=pathlib.Path,
    help="Import from the server a directory with this name.",
)
@ click.option(
    "-o",
    "--outpath",
    "outpath",
    default="./",
    type=pathlib.Path,
    help="Output directory.",
    show_default=True,
)
@ click.option(
    "-r",
    "--repopath",
    "repopath",
    default="./",
    type=pathlib.Path,
    help="Path of data repository",
    envvar="IMPORTER_REPOPATH",
    show_envvar=True
)
@ click.option(
    "--mountpoint",
    "mountpoint",
    default=None,
    type=pathlib.Path,
    help="Mountpoint for remote directory.",
    envvar="IMPORTER_MOUNTPOINT",
    show_envvar=True
)
@ click.option(
    "--server-ip",
    "server_ip",
    default="127.0.0.1",
    help="IP to probe to check remote server",
    envvar="IMPORTER_SERVIP",
    show_envvar=True,
    show_default=True,
)
@ click.option(
    "--server-check/--no-server-check",
    "server_check",
    is_flag=True,
    default=None,
    envvar="IMPORTER_SERVER_CHECK",
    show_envvar=True,
    show_default=True,
    help="Check or skip remote ip."
)
@ click.option(
    "--compress/--no-compress",
    "compress",
    is_flag=True,
    default=None,
    envvar="IMPORTER_COMPRESS",
    help="Compress imported folder"
)
@ click.option(
    "-v",
    "--verbose",
    count=True,
    type=int,
    help="Control verbosity level (repeat to increase).",
    show_default="WARNING"
)
@ click.option(
    "-f",
    "--force",
    "force",
    is_flag=True,
    default=False,
    help="Copy folder even if it already exists at destination"
)
@ click.pass_context
@ main_handle_errors
def main(ctx, **kwargs):
    """Program entry point."""

    set_verbosity(kwargs["verbose"])

    logger.debug(f"{ctx.invoked_subcommand = }")
    logger.debug(f"{kwargs = }")

    remote_repo = build_remote_repo(kwargs)
    if remote_repo is None:
        return 1

    with remote_repo as rem:
        if isinstance(rem, Exception):
            logger.error(rem)
            return 1

        logger.debug(f"{rem = }")

        indir = get_input_directory(kwargs)

        if indir is None:
            logger.error("No input directory selected.")
            return 1

        logger.debug(f"{indir = }")

    return 0


def set_verbosity(level: int):
    """Set the correct verbosity level."""

    if level <= 0:
        logger.setLevel(logging.WARNING)
    elif level == 1:
        logger.setLevel(logging.INFO)
    elif level >= 2:
        logger.setLevel(logging.DEBUG)

    # overrides cli flag
    if "IMPORTER_DEBUG" in os.environ.keys():
        logger.setLevel(logging.DEBUG)
        logger.debug("Logging level set to debug via envvar IMPORTER_DEBUG.")


def build_remote_repo(kwargs) -> Optional[RemoteRepo]:
    """Build the remote repository manager instance."""

    mountpoint = kwargs["mountpoint"]
    server_ip = kwargs["server_ip"]
    server_check = kwargs["server_check"]

    if mountpoint is not None:
        try:
            mountpoint = pathlib.Path(mountpoint)
        except Exception as e:
            logger.error(e)
            return

    try:
        server_ip = ipaddress.ip_address(server_ip)
    except Exception as e:
        logger.error(e)
        return

    ck_status = Status("Checking remote server.")
    ck_st_cb = StatusCB(start=ck_status.start, stop=ck_status.stop)

    mnt_status = Status("Mounting remote repo.")
    mnt_st_cb = StatusCB(start=mnt_status.start, stop=mnt_status.stop)

    return RemoteRepo(
        mountpoint=mountpoint,
        server_ip=server_ip,
        server_ck=server_check,
        ck_st_cb=ck_st_cb,
        mnt_st_cb=mnt_st_cb,
    )


def get_input_directory(kwargs) -> Optional[pathlib.Path]:
    """Get the path for the input directory."""

    today = kwargs["today"]
    datepath = kwargs["datepath"]
    inpath = kwargs["inpath"]
    mountpoint = kwargs["mountpoint"]

    if datepath is not None:
        try:
            datepath = datetime.strptime(f"{datepath}-13", "%Y-%m-%d-%H")
        except Exception as e:
            logger.error(e)
            return

    if inpath is not None:
        try:
            inpath = pathlib.Path(inpath)
        except Exception as e:
            logger.errror(e)
            return

    try:
        mountpoint = pathlib.Path(mountpoint)
    except Exception as e:
        logger.error(e)
        return

    search_st = Status("Searching for matching directories")
    search_st_cb = StatusCB(start=search_st.start, stop=search_st.stop)

    dir = InputDIR(
        today=today,
        date=datepath,
        inpath=inpath,
        root=mountpoint,
        search_cb=search_st_cb,
    )

    logger.debug(f"{dir = }")

    return dir.path


def paths_good(kwargs: Dict) -> bool:
    """Final check for the given input/output paths."""
    logger.debug(f"{kwargs = }")
    inpath = pathlib.Path(kwargs["inpath"]).resolve()
    if not inpath.is_dir():
        logger.error(f"Specified input path {inpath} is not a directory.")
        return False

    outpath = kwargs["outpath"]
    if not outpath.is_dir():
        logger.error(f"Specified output path {outpath} is not a directory.")
        return False

    repopath = kwargs["repopath"]
    if not repopath.is_dir():
        logger.error(
            f"Specified repository path {repopath} is not a directory.")
        return False

    return True


def make_unique_fname(fname: pathlib.Path) -> pathlib.Path:
    """Append a numerical suffix to render a filename unique."""
    fname_new = fname
    i = 1
    while fname_new.exists() or fname_new.is_symlink():
        name = str(fname.name)
        suffixes = ''.join(fname.suffixes)
        basename = name.replace(suffixes, '')
        newname = f"{basename}_{i}{suffixes}"
        fname_new = fname_new.with_name(newname)
        i += 1

    logger.debug(f"{fname_new = }")
    return fname_new


def add_pbar_copyf(copyf, progress: Progress, task: TaskID):
    """Add a progressbar to a copying function."""
    def closure(*args, **kwargs):
        inname = pathlib.Path(args[0]).name
        progress.update(task, description=f"Copying {inname}", advance=1)
        copyf(*args, **kwargs)

    return closure


def process_files(kwargs: Dict) -> int:
    """Copy the files to destination."""
    logger.debug(f"{kwargs = }")
    return 0
