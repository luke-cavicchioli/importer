"""Simple setuptools shim for compatibility purposes. It is also necessary for 
editable installs.
"""
from setuptools import find_packages, setup

setup(
    packages=find_packages(
        exclude="config"
    )
)
