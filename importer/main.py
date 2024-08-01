"""Main function of the program."""

import pathlib
from datetime import date

import click
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from rich.console import Console

cns = Console(width=80)


def default_config_path() -> pathlib.Path:
    thisfile = pathlib.Path(__file__).resolve()
    defconp = thisfile.parents[1].joinpath("config").joinpath("default.toml")
    return defconp


DEFCONP = default_config_path()


class AppSettings(BaseSettings):
    datepath: date | None = Field(
        default=None,
        alias="date",
    )
    inpath: pathlib.Path | None = Field(
        default=None,
    )
    outpath: pathlib.Path | None = Field(
        default=None
    )

    model_config = SettingsConfigDict(
        env_prefix="importer_",
        toml_file=DEFCONP,
        cli_parse_args=False,
        cli_enforce_required=True,
        cli_hide_none_type=False,
        validate_assignment=True,
    )


@click.command(
    help="Import files from a server."
)
@click.option(
    "--today",
    "today",
    is_flag=True,
    help="Import from the server a directory with today's date as a name."
)
@click.option(
    "-d",
    "--date",
    "datepath",
    default=None,
    type=date,
    help="Import from the server a directory with this date as a name."
)
@click.option(
    "-i",
    "--inpath",
    "inpath",
    default=None,
    type=pathlib.Path,
    help="Import from the server a directory with this name."
)
@click.option(
    "-o",
    "--outpath",
    "outpath",
    default="./",
    type=pathlib.Path,
    help="Output directory.",
    show_default=True
)
def main(today, datepath,  inpath, outpath):
    """Program entry point."""
    if today:
        if datepath is not None:
            cns.print("[bold yellow]--today option overrides --date")
        datepath = date.today()
    settings = AppSettings()
    if datepath is not None:
        settings.datepath = datepath
    if inpath is not None:
        settings.inpath = inpath
    if outpath is not None:
        settings.outpath = outpath
    print(settings.model_dump())
