"""Compatibility layer for the production database helpers.

The src/ tree is a legacy rewrite path. Re-export the production DB module so
schema and helper changes stay in one place.
"""

from database.db_client import *  # noqa: F401,F403
