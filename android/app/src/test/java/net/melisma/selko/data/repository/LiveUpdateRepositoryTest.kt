package net.melisma.selko.data.repository

import app.cash.turbine.test
import io.github.jan.supabase.SupabaseClient
import io.mockk.mockk
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * C6/C9: LiveUpdateRepository debounce + catch-up contract.
 *
 * The realtime/session paths need a live Supabase client; the observable
 * invalidation contract (debounce, filtering, catchUp fan-out) is pure and
 * tested here.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class LiveUpdateRepositoryTest {

    private fun makeRepository(): LiveUpdateRepository {
        // SupabaseClient is only used for the channel; the tested paths never
        // touch it.
        return LiveUpdateRepository(mockk<SupabaseClient>(relaxed = true))
    }

    private fun invalidation(resource: String, operation: String = "UPDATE"): String {
        return buildJsonObject {
            put("resource", resource)
            put("operation", operation)
            put("entity_id", "entity-1")
            put("occurred_at", "2026-08-10T00:00:00Z")
        }.toString()
    }

    @Test
    fun `an invalidate for events triggers exactly one refetch after debounce`() = runTest {
        val repo = makeRepository()
        repo.invalidations.test {
            repo.handleInvalidate(jsonObject(invalidation("events")))
            val inv = awaitItem()
            assertEquals("events", inv.resource)
            assertEquals("UPDATE", inv.operation)
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `a payload for an unlisted resource is ignored`() = runTest {
        val repo = makeRepository()
        repo.invalidations.test {
            repo.handleInvalidate(jsonObject(invalidation("photos")))
            // Debounce window passes with no emission for unlisted resources.
            kotlinx.coroutines.delay(600)
            expectNoEvents()
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `five invalidations within the debounce window produce one refetch`() = runTest {
        val repo = makeRepository()
        repo.invalidations.test {
            repeat(5) {
                repo.handleInvalidate(jsonObject(invalidation("events", operation = "UPDATE-$it")))
            }
            val inv = awaitItem()
            assertEquals("events", inv.resource)
            // Trailing collapse: only the last of the burst is delivered.
            assertEquals("UPDATE-4", inv.operation)
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `catchUp emits all four resources`() = runTest {
        val repo = makeRepository()
        repo.invalidations.test {
            repo.catchUp()
            val resources = mutableSetOf<String>()
            repeat(4) {
                resources.add(awaitItem().resource)
            }
            assertEquals(setOf("events", "event_sources", "emails", "integrations"), resources)
            assertTrue(resources.size == 4)
            cancelAndIgnoreRemainingEvents()
        }
    }

    private fun jsonObject(raw: String) =
        kotlinx.serialization.json.Json.parseToJsonElement(raw) as kotlinx.serialization.json.JsonObject
}
