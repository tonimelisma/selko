"""Load the real database fixtures for the standalone staging drill."""

import pytest

from tests.integration.conftest import *  # noqa: F403,F401
from tests.integration.test_integration_email_ingestion_v2 import synced_integration


@pytest.fixture
async def pg_pool(staging_config):
    """Use the staging session pooler for every staging drill assertion."""
    from selko.services.pg import create_pool

    if staging_config is None:
        pytest.skip("Staging config is not available")
    pool = await create_pool(staging_config)
    yield pool
    await pool.close()
