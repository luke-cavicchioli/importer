# List available recipes
list:
    @just -l

# Update requirements.txt if pyproject.toml has changed
upd_req:
    checkexec requirements.txt pyproject.toml setup.py -- just _update_requirements

# Perform the actual requirements update
_update_requirements:
    pip-compile --output-file=requirements.txt pyproject.toml
    pip install -r requirements.txt
    pip install -e ./

# Live command to run during development
live:
    watchexec --workdir ./ -prc -- just _live_cmd

_live_cmd:
    importer 
