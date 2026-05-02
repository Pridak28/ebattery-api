"""pytest plugin that pre-imports numpy + pandas.

Loaded before pytest-cov initializes (via -p / autouse via pyproject) to
avoid the numpy reload bug under pytest-cov 7.x + numpy 2.x. See conftest.py
for full diagnosis.
"""
import numpy  # noqa: F401
import pandas  # noqa: F401
