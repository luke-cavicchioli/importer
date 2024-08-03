"""Main function of the program."""

import ipaddress
import logging
import os
import pathlib
import sys
import warnings
from datetime import date
from typing import Optional

import click
import sh
from rich.console import Console
from rich.logging import RichHandler
from rich.style import Style

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
        "datepath": date.today(),
        "inpath": None
    })
    return newargs


def set_verbosity(level: int):
    """Set the correct verbosity level."""

    if level <= 0:
        logger.setLevel(logging.WARNING)
    elif level == 1:
        logger.setlevel(logging.INFO)
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
        unit = time_line[4]
        time_str = f"Ping ({unit}): min {tmin}, max {tmax}"

        logger.info(
            f"Server check for {ip}:\n\t{loss_str}\n\t{time_str}")
    except Exception as e:
        warnings.warn(f"Error while parsing ping response: {e}. Continuing.")

    return True


def mount_repo(mountpoint: Optional[str]) -> bool:
    logger.debug(f"{mountpoint = }")
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


@click.group(
    help="Import files from a server.",
    invoke_without_command=True,
    context_settings=CONTEXT_SETTINGS,
)
@click.option(
    "--today",
    "today",
    is_flag=True,
    help="Import from the server a directory with today's date as a name.",
)
@click.option(
    "-d",
    "--date",
    "datepath",
    default=None,
    type=date,
    help="Import from the server a directory with this date as a name.",
)
@click.option(
    "-i",
    "--inpath",
    "inpath",
    default=None,
    type=pathlib.Path,
    help="Import from the server a directory with this name.",
)
@click.option(
    "-o",
    "--outpath",
    "outpath",
    default="./",
    type=pathlib.Path,
    help="Output directory.",
    show_default=True,
)
@click.option(
    "-r",
    "--repopath",
    "repopath",
    default=None,
    type=pathlib.Path,
    help="Path of data repository",
    envvar="IMPORTER_REPOPATH",
    show_envvar=True
)
@click.option(
    "--mountpoint",
    "mountpoint",
    default=None,
    type=pathlib.Path,
    help="Mountpoint for remote directory.",
    envvar="IMPORTER_MOUNTPOINT",
    show_envvar=True
)
@click.option(
    "--server-ip",
    "server_ip",
    default="127.0.0.1",
    help="IP to probe to check remote server",
    envvar="IMPORTER_SERVIP",
    show_envvar=True,
    show_default=True,
)
@click.option(
    "--server-check/--no-server-check",
    "server_check",
    is_flag=True,
    default=None,
    envvar="IMPORTER_SERVER_CHECK",
    show_envvar=True,
    show_default=True,
    help="Check or skip remote ip."
)
@click.option(
    "--compress/--no-compress",
    "compress",
    is_flag=True,
    default=False,
    envvar="IMPORTER_COMPRESS",
    help="Compress imported folder"
)
@click.option(
    "-v",
    "--verbose",
    count=True,
    type=int,
    help="Control verbosity level (repeat to increase).",
    show_default="WARNING"
)
@click.pass_context
@main_handle_errors
def main(ctx, **kwargs):
    """Program entry point."""

    set_verbosity(kwargs["verbose"])

    logger.debug(f"{ctx.invoked_subcommand = }")

    kwargs = handle_today_arg(kwargs)
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
            mount_repo(mountpoint)
    else:
        logger.info("No mountpoint specified.")

    return 0
