"""Main function."""

from pydantic_settings import CliApp

from .cli import App


def main():
    CliApp.run(App)
