import logging
import warnings
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import (BaseSettings, CliApp, CliSubCommand,
                               SettingsConfigDict)
from rich.console import Console
from rich.logging import RichHandler

cns = Console(width=80)
log_handler = RichHandler(
    console=cns,
    show_path=False,
    show_time=False
)

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

logger = logging.getLogger(__file__)
logger.addHandler(log_handler)
logger.propagate = 0


class BackupMethods(IntEnum):
    gdrive = 0


class Verbosity(StrEnum):
    error = "error"
    warning = "warning"
    info = "info"
    debug = "debug"

    def __int__(self):
        if self.value == "error":
            return logging.ERROR
        elif self.value == "warning":
            return logging.WARN
        elif self.value == "info":
            return logging.INFO
        elif self.value == "debug":
            return logging.DEBUG
        else:
            return logging.NOTSET


def set_verbosity(lvl: Verbosity):
    logging.basicConfig(level=int(lvl))


class ImporterCommand(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="importer_")
    source_root: Path = Field(description="Root of the source filesystem")
    local_root: Path = Field(description="Root of the local repository")
    backup_root: Optional[Path] = Field(
        description="Root of the backup repository",
        default=None
    )
    backup_method: Optional[BackupMethods] = Field(
        description="Method to backup the files",
        default=None
    )
    datepath_fmt: str = Field(
        description="Format of the path under source_root if a date is given (strftime syntax)",
        default="%Y/%Y-%m/%Y-%m-%d"
    )
    verbose: Verbosity = Field(
        default=Verbosity.error
    )


class Get(ImporterCommand):
    """Get a directory from the source."""

    def cli_cmd(self) -> None:
        set_verbosity(self.verbose)
        logger.debug(self)


class Archive(ImporterCommand):
    """Archive a directory (remove from local, keep in backup)."""

    def cli_cmd(self) -> None:
        set_verbosity(self.verbose)
        logger.debug(self)


class App(BaseSettings, cli_parse_args=True):
    get: CliSubCommand[Get]
    upd: CliSubCommand[Archive]

    def cli_cmd(self) -> None:
        CliApp.run_subcommand(self)
