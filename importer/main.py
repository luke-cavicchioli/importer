"""Main function of the program."""

import logging
import pathlib
import warnings
from datetime import date

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.pretty import pretty_repr

termw = 80

cns = Console(width=termw)

log_handler = RichHandler(
    console=cns,
    show_path=False,
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
    default=None,
    help="IP to probe to check remote server",
    envvar="IMPORTER_SERVIP",
    show_envvar=True,
)
@click.option(
    "--server-check/--no-server-check",
    is_flag=True,
    default=True,
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
def main(ctx, **kwargs):
    """Program entry point."""
    set_verbosity(kwargs["verbose"])
    cns.rule("IMPORTER")
    logger.debug(f"Invoked subcommand: {ctx.invoked_subcommand}")
    kwargs = handle_today_arg(kwargs)
    logger.debug(pretty_repr(kwargs))

    cns.rule()
