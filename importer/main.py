"""Main function of the program."""

import pathlib
from datetime import date

import click
import rich.console as rconsole

from . import defaults

termw = 80

cns = rconsole.Console(width=termw)

CONTEXT_SETTINGS = {
    "default_map": defaults.default_map,
    "terminal_width": termw
}


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
    cns.rule("IMPORTER")
    cns.print("Args:")
    cns.print(kwargs)

    cns.rule()
