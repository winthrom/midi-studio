#!/usr/bin/env python3
from setuptools import setup, find_packages

setup(
    name="midi-studio",
    version="0.4.0",
    description="MIDI notation editor and synthesizer",
    author="Michael Winthrop",
    author_email="michael.f.winthrop@gmail.com",
    license="GPL-3.0-or-later",
    packages=find_packages(),
    install_requires=[
        "mido>=1.2.0",
        "python-rtmidi>=1.4.0",
        "pyfluidsynth>=1.2.0",
    ],
    entry_points={
        "console_scripts": [
            "midi-studio=main:main",
        ],
    },
    python_requires=">=3.8",
)
