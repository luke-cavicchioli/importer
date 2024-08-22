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

from .remote import RemoteRepo, StatusCB

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

    remote = build_remote_repo(kwargs)
    logger.debug(f"{remote = }")

    # kwargs = handle_today_arg(kwargs)
    # kwargs, cancelled = handle_datedir(kwargs)
    # logger.debug(f"{cancelled = }")
    #
    # inpath = kwargs["inpath"]
    # logger.debug(f"{inpath = }")
    # datepath = kwargs["datepath"]
    # logger.debug(f"{datepath = }")
    #
    # # If there was no input, Interactively get the input path.
    # # Test for cancelled is needed, as otherwise would want inpath if user
    # # cancels datedir selection with C-c
    # is_inpath_needed = inpath is None and datepath is None and not cancelled
    # if is_inpath_needed:
    #     inpath = get_inpath(mountpoint)
    #
    # # Put datepath into inpath if there was no inpath given, and datepath was
    # # given
    # is_datepath_selected = inpath is None and datepath is not None
    # if is_datepath_selected:
    #     inpath = datepath
    #
    # # Because now remote is mounted, return code needs to be given from
    # # process files, otherwise no unmounting.
    # ret = 0
    # if inpath is not None:
    #     kwargs["inpath"] = mountpoint.joinpath(inpath)
    #     ret = process_files(kwargs)
    # else:
    #     logger.error("No input directory selected.")
    #     ret = 1
    #
    # with cns.status(f"Unmounting {mountpoint}"):
    #     unmount_remote(mountpoint)

    return 0


def handle_today_arg(kwargs):
    """Sets the datepath if today is set."""

    if not kwargs["today"]:
        return kwargs

    if kwargs["datepath"] is not None:
        warnings.warn("--today will override --date")
    if kwargs["inpath"] is not None:
        warnings.warn("--today will override --inpath")

    newargs = kwargs.copy()
    newargs.update({
        "datepath": date.today().strftime("%Y-%m-%d"),
        "inpath": None
    })
    return newargs


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


def build_remote_repo(kwargs):
    """Build the remote repository manager instance."""

    mountpoint = kwargs["mountpoint"]
    server_ip = kwargs["server_ip"]
    server_check = kwargs["server_check"]

    try:
        mountpoint = pathlib.Path(mountpoint)
    except Exception as e:
        logger.error(e)
        return 1

    try:
        server_ip = ipaddress.ip_address(server_ip)
    except Exception as e:
        logger.error(e)
        return 1

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


def ping_server(flag: bool, ip: str) -> bool:
    """Checks server if needed."""
    localhost = ipaddress.ip_address("127.0.0.1")
    if ip == localhost and flag is None:
        warnings.warn(
            "server-ip is localhost, skipping check. Use --server-check to force.")
        return True
    ret = sh.ping(
        str(ip),
        "-l3",
        "-c3",
        "-W2",
        _return_cmd=True,
        _ok_code=[0, 1, 2],
        _err_to_out=True
    )
    if ret.exit_code == 1:
        logger.error(f"Server at {ip} did not answer.")
        return False

    if ret.exit_code == 2:
        logger.error(f"Error while checking server at {ip}:\n{ret}")
        return False

    try:
        ret = ret.split("\n")[-3:-1]

        loss_line = ret[0].split(" ")
        tr = loss_line[0]
        rec = loss_line[3]
        loss_str = f"{tr}/{rec} packets received."

        time_line = ret[1].split(" ")
        times = time_line[3].split("/")
        tmin = times[0]
        tmax = times[1]
        unit = time_line[4][:-1]
        time_str = f"Ping ({unit}): min {tmin}, max {tmax}"

        logger.info(
            f"Server check for {ip}:\n\t{loss_str}\n\t{time_str}")
    except Exception as e:
        warnings.warn(f"Error while parsing ping response: {e}. Continuing.")

    return True


def mount_remote(mountpoint: Optional[str]) -> bool:
    """Mount remote directory to specified mountpoint."""
    logger.debug(f"{mountpoint = }")
    ret = sh.mountpoint(
        mountpoint,
        "-q",
        _return_cmd=True,
        _ok_code=[0, 32],
        _err_to_out=True
    )
    if ret.exit_code == 0:
        logger.debug(f"{mountpoint} is already mounted.")
        return True

    ret = sh.mount(
        mountpoint,
        _return_cmd=True,
        _ok_code=[0, 1, 2, 4, 8, 16, 32, 64],
        _err_to_out=True
    )

    if ret.exit_code == 0:
        return True

    logger.error(ret)

    return False


def unmount_remote(mountpoint: Optional[str]):
    """Try to unmount the remote directory."""
    if mountpoint is not None:
        ret = sh.umount(
            mountpoint,
            _return_cmd=True,
            _ok_code=[0, 1, 2, 4, 8, 16, 32, 64]
        )
        if ret.exit_code != 0:
            warnings.warn("Could not unmount the remote directory.")
        logger.debug(f"Unmounting {mountpoint}: {ret.exit_code = }")
    else:
        logger.debug("Skipping unmounting")


def validate_dir(dir: str) -> Union[bool, str]:
    if os.path.isdir(dir):
        return True
    else:
        return "Not a directory"


def get_inpath(root: Optional[str]) -> pathlib.Path:
    """Interactively get the input path."""
    root_path = None
    if root is None:
        root_path = pathlib.Path("./").resolve()
    else:
        root_path = pathlib.Path(root).resolve()
    logger.debug(f"{root_path = }")

    ans = questionary.path(
        message="Choose input path: ",
        default=str(root_path),
        only_directories=True,
        validate=validate_dir
    ).ask()
    logger.debug(f"{ans = }")

    return pathlib.Path(ans) if ans is not None else None


def handle_datedir(kwargs):
    """Find and select datedir, or abort selection."""
    datepath = kwargs["datepath"]
    inpath = kwargs["inpath"]
    mountpoint = kwargs["mountpoint"]
    selected = None

    if mountpoint is None:
        mountpoint = os.getcwd()
    mountpoint = pathlib.Path(mountpoint)

    if datepath is not None:
        searchdate = datetime.strptime(f"{datepath}-13", "%Y-%m-%d-%H")
        with cns.status("Searching for matching directories"):
            found = find_datedir(searchdate, mountpoint)
        selected = select_datedir(found)

    if selected is not None:
        datepath = selected

    newargs = kwargs.copy()
    newargs.update({"inpath": inpath, "datepath": datepath})

    return (newargs, selected is None)


def datescore_dir(dir: pathlib.Path, target: datetime) -> int:
    mtime = datetime.fromtimestamp(os.stat(dir).st_mtime)
    delta = mtime - target
    return abs(int(delta.total_seconds()))


def find_datedir(date: datetime, root: pathlib.Path, n=10) -> List[pathlib.Path]:
    """Find best matching directories in the root path."""
    found = []

    for curr, subdns, _ in os.walk(root):
        # append current directory if none visited
        if len(found) == 0:
            found.append((curr, pathlib.Path(curr), datescore_dir(curr, date)))

        # find scores for all sub-directories
        subdps = [(d, pathlib.Path(curr).joinpath(d).resolve())
                  for d in subdns]
        subdss = [(d, p, datescore_dir(p, date)) for d, p in subdps]

        # keep only subdss members that would be in top ten
        subdss.sort(key=lambda x: x[2])
        found[:] = found + subdss
        found.sort(key=lambda x: x[2])
        found[:] = found[:min(len(found), n)]
        max_found = found[-1][2]
        subdss[:] = [(d, s) for d, _, s in subdss if s <= max_found]

        # traverse only subdirectories in subdss (i.e. directories in top ten)
        subdns[:] = [d for d, _ in subdss]

    found = [str(x[1]) for x in found]
    return found


def select_datedir(found: List[pathlib.Path]) -> pathlib.Path:
    foundstr = [str(x) for x in found]
    ans = questionary.select(
        "Best matches:",
        instruction="Enter to select the desired directory, C-c to cancel",
        choices=foundstr,
        show_selected=True
    ).ask()
    logger.debug(f"{ans = }")
    return ans


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
