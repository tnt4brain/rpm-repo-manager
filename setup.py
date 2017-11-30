#!/usr/bin/env python
from setuptools import setup, find_packages, Command
import sys

setup(
    name="rpm_repo_manager",
    version="0.0.1",
    description="RPM manager",
    author="Sergey Pechenko",
    author_email="10977752+tnt4brain@users.noreply.github.com",
    url="https://github.com/tnt4brain/rpm-repo-manager",
    packages=find_packages(),
    entry_points="""
        [console_scripts]
        rpm-repo-manager=rpm_repo_manager:main
    """,
    long_description="""Manages and update RPM repository (requires 'createrepo' to be installed)"""
)
