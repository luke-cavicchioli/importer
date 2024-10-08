"""Main function of the program."""

import ipaddress
import logging
import os
import pathlib
import warnings
from datetime import datetime
from typing import Any, Dict, Optional, Union

import click
import questionary
from rich import box
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import Progress
from rich.status import Status
from rich.table import Table

from .fileproc import FileProcessor
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


def formatwarning(
        message: Warning | str,
        category: type[Warning],
        filename: str,
        lineno: int,
        line: Optional[str] = None
) -> str:
    """Format warning messages."""
    # Call each name not to have unused variables.
    category
    filename
    lineno
    line
    return str(message)


warnings.formatwarning = formatwarning
warn_logger = logging.getLogger("py.warnings")
warn_logger.addHandler(log_handler)


CONTEXT_SETTINGS = {
    "terminal_width": termw
}


CliOption = Union[str, int, bool, None]


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
    show_envvar=True,
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
def main(ctx: Any, **kwargs: CliOption) -> int:
    """Program entry point."""
    set_verbosity(kwargs["verbose"])

    cns.rule("IMPORTER")

    logger.debug(f"{ctx.invoked_subcommand = }")
    logger.debug(f"{kwargs = }")

    ret = 0
    try:
        ret = imprtf(kwargs)
    except Exception as e:
        logger.error(f"Uncaught error: {e}")
        ret = 55
    except KeyboardInterrupt:
        logger.error("Interrupted by user")
        ret = 125

    if ret == 0:
        cns.rule()
    else:
        cns.rule(style="red")

    return ret


def set_verbosity(level: int):
    """Set the correct verbosity level.

    The verbosity level is overridden if the environment variable
    "IMPORTER_DEBUG" is set; in this case, the logging level will be DEBUG.

    Values:
        - 0: WARNING
        - 1: INFO
        - 2: DEBUG

    :param level: Verbosity level.
    """
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


def imprtf(kwargs: Dict["str", CliOption]):
    """Import the files.

    :param kwargs: The keyword arguments from the main function.
    """
    remote_repo = build_remote_repo(kwargs)
    if remote_repo is None:
        return 121  # EREMOTEIO

    with remote_repo as rem:
        if isinstance(rem, Exception):
            logger.error(rem)
            return 121  # EREMOTEIO

        logger.debug(f"{rem = }")

        indir = get_input_directory(kwargs)

        if indir is None:
            logger.error("No input directory selected.")
            return 125  # ECANCELED

        logger.debug(f"{indir = }")

        outpath = kwargs["outpath"].resolve()
        repopath = kwargs["repopath"].resolve()
        if not paths_good(indir, outpath, repopath):
            return 2  # ENOENT

        compress = kwargs["compress"]
        force = kwargs["force"]
        ret = process(indir, outpath, repopath, compress, force)

        if ret != 0:
            return ret

    return 0


def build_remote_repo(kwargs: Dict) -> Optional[RemoteRepo]:
    """Build the remote repository manager instance.

    :param kwargs: The keyword arguments to the main function.
    :return: An instance of RemoteRepo with the required settings if successful,
        otherwise None
    """
    mountpoint = kwargs["mountpoint"]
    server_ip = kwargs["server_ip"]
    server_check = kwargs["server_check"]

    if mountpoint is not None:
        try:
            mountpoint = pathlib.Path(mountpoint)
        except Exception as e:
            logger.error(e)
            return None

    try:
        server_ip = ipaddress.ip_address(server_ip)
    except Exception as e:
        logger.error(e)
        return None

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


def get_input_directory(kwargs: Dict[str, CliOption]) -> Optional[pathlib.Path]:
    """Get the path for the input directory.

    :param kwargs: The keyword arguments to the main function.
    :return: An instance of Path if the search is successful, otherwise None.
    """
    today = kwargs["today"]
    datepath = kwargs["datepath"]
    inpath = kwargs["inpath"]
    mountpoint = kwargs["mountpoint"]

    if datepath is not None:
        try:
            datepath = datetime.strptime(f"{datepath}-13", "%Y-%m-%d-%H")
        except Exception as e:
            logger.error(e)
            return None

    if inpath is not None:
        try:
            inpath = pathlib.Path(inpath)
        except Exception as e:
            logger.error(e)
            return None

    try:
        mountpoint = pathlib.Path(mountpoint)
    except Exception as e:
        logger.error(e)
        return None

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


def paths_good(inpath: pathlib.Path, outpath: pathlib.Path, repopath: pathlib.Path) -> bool:
    """Check for the given input/output paths.

    :param inpath: The input directory path.
    :param outpath: The path to which the files should be symlinked.
    :param repopath: The path to which the files should be copied.
    :return: If the paths are correct (True) or not (False).
    """
    if not inpath.is_dir():
        logger.error(f"Specified input path {inpath} is not a directory.")
        return False

    if not outpath.is_dir():
        logger.error(f"Specified output path {outpath} is not a directory.")
        return False

    if not repopath.is_dir():
        logger.error(
            f"Specified repository path {repopath} is not a directory.")
        return False

    return True


def process(
        indir: pathlib.Path,
        outpath: pathlib.Path,
        repopath: pathlib.Path,
        compress: bool,
        force: bool
) -> int:
    """Process the files to destination.

    :param indir: The path to the input root directory.
    :param outpath: The path to the output symlink location.
    :param repopath: The path to the repository location.
    :param force: Whether existing files should be overwritten.
    :return: An exit code, following (as much as possible) errno conventions.
    """
    proc = FileProcessor(
        indir=indir,
        outpath=outpath,
        repopath=repopath,
        compress=compress,
        force=force,
        ignore_patterns=["*.sis"]
    )

    if not process_confirm(proc):
        return 125

    nfiles = proc.count_files()
    logger.info(f"There are {nfiles} files to process.")
    pbar = Progress(console=cns, transient=True)
    ctask = pbar.add_task(total=nfiles, description="Processing files:")

    def pbar_upd(description: str):
        pbar.update(ctask, advance=1, description=description)

    pbar.start()
    ret = proc(cb=pbar_upd)
    pbar.stop()
    cns.print("[bold green]Done.")

    return ret


def process_confirm(proc: FileProcessor) -> bool:
    """Ask to confirm the processing of files.

    :param proc: The file processor from which the information should be pulled.
    :return: Whether the user confirmed.
    """
    tbl = Table(
        show_header=False,
        width=cns.width,
        box=box.SIMPLE,
        padding=(0, 0, 0, 0),
        collapse_padding=True,
        pad_edge=False
    )
    tbl.add_column(justify="left")
    tbl.add_column(justify="left")

    tbl.add_row("Source", str(proc.src), style="green")

    link_dst = proc.link_path
    dst_root = proc.dst
    if link_dst is None:
        tbl.add_row("Destination", str(dst_root), style="yellow")
    else:
        tbl.add_row("Repo destination", str(dst_root), style="blue")
        tbl.add_row("Link destination", str(link_dst), style="yellow")

    if proc.compress:
        tbl.add_row("Method", "Archive of source tree")
    else:
        tbl.add_row("Method", "Copy of source tree")

    if proc.force:
        tbl.add_row("Force", "Yes", style="red")
    else:
        tbl.add_row("Force", "No")

    cns.print(tbl)

    ans = questionary.confirm("Confirm?").ask()
    logger.debug(f"{ans = }")
    if ans is not None:
        return ans

    return False
