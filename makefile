all: requirements.txt

requirements.txt: pyproject.toml
	pip-compile > requirements.txt
	pip-sync
