"""Tier 2: prove the grant posture where it is actually broken.

Local Supabase and the hosted platform do not ship the same default ACL:

    local  postgres -> {postgres=X/postgres}
    cloud  postgres -> {postgres=X,anon=X,authenticated=X,service_role=X}

Measured 2026-08-21. A function created by a migration is therefore private on
creation locally and public on creation in staging and production. That is why
the exposure -- 56/56 SECURITY DEFINER functions callable by anon on staging,
45/45 on production -- was invisible to every local gate for months, including
the gate named for this property.

The local guard in test_schema_contract.py is a regression test. This is the
one that can fail for the real reason, so it runs against real cloud Postgres.
"""

import pytest

from tests.integration.test_schema_contract import AUTHENTICATED_EXECUTABLE_FUNCTIONS


ANON_EXECUTABLE_QUERY = """
SELECT p.proname AS name,
       pg_get_function_identity_arguments(p.oid) AS args,
       has_function_privilege('anon', p.oid, 'EXECUTE') AS anon_executes,
       has_function_privilege('authenticated', p.oid, 'EXECUTE') AS authenticated_executes
FROM pg_proc AS p
JOIN pg_namespace AS n ON n.oid = p.pronamespace
WHERE n.nspname = 'public' AND p.prosecdef
ORDER BY p.proname
"""


@pytest.mark.staging
@pytest.mark.integration
@pytest.mark.asyncio
async def test_staging_grants_no_security_definer_execution_to_anon(staging_pg_pool):
    rows = await staging_pg_pool.fetch(ANON_EXECUTABLE_QUERY)
    assert rows, "no SECURITY DEFINER functions found; the query is wrong"
    exposed = [f"{row['name']}({row['args']})" for row in rows if row["anon_executes"]]
    assert not exposed, (
        f"{len(exposed)} SECURITY DEFINER functions are callable with the published "
        f"anon key: {exposed[:10]}{'...' if len(exposed) > 10 else ''}"
    )


@pytest.mark.staging
@pytest.mark.integration
@pytest.mark.asyncio
async def test_staging_grants_only_the_contract_set_to_authenticated(staging_pg_pool):
    rows = await staging_pg_pool.fetch(ANON_EXECUTABLE_QUERY)
    granted = {row["name"] for row in rows if row["authenticated_executes"]}
    expected = set(AUTHENTICATED_EXECUTABLE_FUNCTIONS)
    assert granted == expected, (
        f"unexpected={sorted(granted - expected)}, missing={sorted(expected - granted)}"
    )
