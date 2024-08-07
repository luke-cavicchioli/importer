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
from datetime import date, datetime
from typing import Dict, List, Optional, Union

import click
import questionary
import sh
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import Progress, TaskID
from rich.style import Style
from thefuzz import fuzz

termw = 80

cns = Console(width=termw)

log_handler = RichHandler(
    console=cns,
    show_path=False,
    show_time=False,
)
logger = logging.getLogger(__name__)
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
    """Stuff to do before and after the main function """
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
        datepath = datetime.strptime(datepath, "%Y-%m-%d")
        with cns.status("Searching for matching directories"):
            found = find_datedir(datepath, mountpoint)
        selected = select_datedir(found)

    if selected is not None:
        datepath = selected

    newargs = kwargs.copy()
    newargs.update({"inpath": inpath, "datepath": datepath})

    return (newargs, selected is not None)


def filterscore_subdirs(dirpath, dirnames, target):
    """Sort and filter the subdirectories according to score."""
    dirnames = sorted(
        dirnames,
        key=lambda x: fuzz.partial_ratio(str(x), target),
        reverse=True
    )
    subdirs = [pathlib.Path(dirpath).joinpath(d) for d in dirnames]
    scores = [(s, fuzz.partial_ratio(str(s), target)) for s in subdirs]
    curr_score = fuzz.partial_ratio(str(dirpath), target)
    return [s[0] for s in scores if s[1] > curr_score]


def find_datedir(date: datetime, root: pathlib.Path, n=10) -> List[pathlib.Path]:
    """Find best matching directories in the root path."""
    target = date.strftime("%Y %m %d")
    logger.debug(f"{target = }")
    found = []

    for dirpath, dirnames, _ in os.walk(root):

        dirnames[:] = filterscore_subdirs(dirpath, dirnames, target)

        if len(dirnames) == 0:
            found.append(dirpath)
            logger.debug(f"Appending to found: {dirpath}")

        if len(found) >= n:
            break

    found = [pathlib.Path(p) for p in found]

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


def do_nothing(*args, **kwargs):
    """Do nothing function, don't copy anything."""
    # logger.debug(f"{args =}, {kwargs = }")


def copy_tree(
    inpath: pathlib.Path,
    destpath: pathlib.Path,
    selected: List[str],
    force: bool,
    copyf=shutil.copy2
) -> int:
    """Copy the selected files and folders, display a nice progress bar."""

    nfiles = [0]

    def countfiles(*_):
        nfiles[0] += 1

    ls = [x.name for x in os.scandir(inpath)]
    ignored = set(ls) - set(pathlib.Path(x).name for x in selected)
    ignored.add("*.sis")
    logger.debug(f"{ignored = }")

    ignore = shutil.ignore_patterns(*ignored)

    tempdir = tempfile.TemporaryDirectory()
    shutil.copytree(
        inpath,
        tempdir.name,
        copy_function=countfiles,
        dirs_exist_ok=True,
        ignore=ignore
    )
    tempdir.cleanup()

    nfiles = nfiles[0]
    logger.debug(f"{nfiles = }")

    with Progress(console=cns, transient=True) as progress:
        task = progress.add_task("Copying file", total=nfiles)

        nice_copyf = add_pbar_copyf(copyf, progress, task)

        try:
            shutil.copytree(
                inpath,
                destpath,
                dirs_exist_ok=force,
                copy_function=nice_copyf,
                ignore=ignore
            )
            pass
        except FileExistsError as e:
            logger.error(e)
            return 1

    cns.print("[bold yellow]Done")

    return 0


def copy_files(kwargs: Dict) -> int:
    """Copy the files to destination."""

    if not paths_good(kwargs):
        return 1

    inpath = kwargs["inpath"].resolve()
    outpath = kwargs["outpath"].resolve()
    repopath = kwargs["repopath"].resolve()
    destpath = repopath.joinpath(inpath.name).resolve()
    force = kwargs["force"]
    compress = kwargs["compress"]

    if destpath.exists():
        if force:
            logger.info(
                f"{destpath.absolute()} exists, it will be overwritten."
            )
        else:
            logger.error(
                f"{destpath.absolute()} exists. Use --force to overwrite."
            )
            return 1

    ls = [x.path for x in os.scandir(inpath)]
    choices = [questionary.Choice(x, checked=True) for x in ls]
    selected = questionary.checkbox(
        "Select files to copy:", choices=choices).ask()

    if len(selected) == 0:
        logger.warning("No files selected for copy. Done.")
        return 0

    if compress is None:
        ans = questionary.confirm("Copy file to compressed archive?").ask()
        compress = ans if ans is not None else False

    copyf = do_nothing if compress else shutil.copy2
    destpath = destpath.with_suffix(".zip") if compress else destpath

    copydir = tempfile.TemporaryDirectory(dir=repopath)
    copypath = pathlib.Path(copydir.name)

    logger.debug(f"{inpath = }")
    logger.debug(f"{destpath = }")
    logger.debug(f"{selected = }")
    logger.debug(f"{force = }")
    logger.debug(f"{compress = }")
    logger.debug(f"{copypath = }")

    ret = copy_tree(inpath, copypath, selected, force, copyf)
    ret = 0
    if ret != 0:
        return ret

    if not compress:
        os.rename(copypath, destpath)
    copydir.cleanup()

    if outpath != repopath:
        linkdest = outpath.joinpath(destpath.name).absolute()
        linkdest = make_unique_fname(linkdest)

        logger.debug(f"{destpath = }, {linkdest = }")
        os.symlink(destpath, linkdest)

    return 0


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

    mountpoint = kwargs["mountpoint"]
    server_ip = kwargs["server_ip"]

    if mountpoint is not None:
        try:
            server_ip = ipaddress.ip_address(server_ip)
        except ValueError as e:
            logger.error(f"server_ip value {e}")
            return 1
        logger.debug(f"{server_ip = }")

        with cns.status("Checking remote server"):
            server_ok = ping_server(kwargs["server_check"], server_ip)

        if not server_ok:
            logger.error("Could not connect to server. Exiting.")
            return 1

        with cns.status("Mounting remote repository"):
            mount_remote(mountpoint)
    else:
        logger.info("No mountpoint specified.")

    kwargs = handle_today_arg(kwargs)
    kwargs, cancelled = handle_datedir(kwargs)

    inpath = kwargs["inpath"]
    logger.debug(f"{inpath = }")
    datepath = kwargs["datepath"]
    logger.debug(f"{datepath = }")

    is_inpath_needed = inpath is None and datepath is None and not cancelled
    if is_inpath_needed:
        inpath = get_inpath(mountpoint)

    is_datepath_selected = inpath is None and datepath is not None
    if is_datepath_selected:
        inpath = datepath

    ret = 0
    if inpath is not None:
        kwargs["inpath"] = mountpoint.joinpath(inpath)
        ret = copy_files(kwargs)
    else:
        logger.error("No input directory selected.")
        ret = 1

    with cns.status(f"Unmounting {mountpoint}"):
        unmount_remote(mountpoint)

    return ret
