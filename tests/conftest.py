"""Shared test fixtures and configuration for the Agentic BFF SDK test suite."""

import pytest
from hypothesis import settings

# Configure Hypothesis default profile with 100 examples per property test
settings.register_profile("default", max_examples=100)
settings.register_profile("ci", max_examples=200)
settings.load_profile("default")
