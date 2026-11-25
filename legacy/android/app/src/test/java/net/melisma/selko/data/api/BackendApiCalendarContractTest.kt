package net.melisma.selko.data.api

import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class BackendApiCalendarContractTest {
    private val json = Json { ignoreUnknownKeys = true }

    @Test
    fun `calendar provider defaults to Google for older backends`() {
        val calendars = json.decodeFromString<List<BackendApiClient.Calendar>>(
            """[{"id":"primary","name":"Me","is_primary":true,"is_selected":true}]"""
        )
        assertEquals(BackendApiClient.Calendar.PROVIDER_GOOGLE_CALENDAR, calendars.single().provider)
        assertFalse(calendars.single().isOutlook)
    }

    @Test
    fun `Outlook calendars keep their opaque id unchanged`() {
        val calendars = json.decodeFromString<List<BackendApiClient.Calendar>>(
            """[{"id":"outlook:AAMkAD=/x+y","name":"Work","is_primary":false,"is_selected":false,"provider":"outlook"}]"""
        )
        val calendar = calendars.single()
        assertTrue(calendar.isOutlook)
        assertEquals("outlook:AAMkAD=/x+y", calendar.id)
    }
}
