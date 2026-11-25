package net.melisma.selko.data.model

import kotlinx.serialization.json.Json
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class CalendarCapabilityTest {

    private val graphCalendarScope = "https://graph.microsoft.com/Calendars.ReadWrite"

    private fun row(
        provider: IntegrationProvider,
        status: IntegrationStatus = IntegrationStatus.ACTIVE,
        scopes: List<String>? = null
    ) = Integration(
        id = provider.name,
        userId = "user-1",
        provider = provider,
        status = status,
        scopes = scopes
    )

    @Test
    fun `active Google Calendar can write`() {
        assertTrue(row(IntegrationProvider.GOOGLE_CALENDAR).canWriteCalendar)
        assertTrue(listOf(row(IntegrationProvider.GOOGLE_CALENDAR)).hasWritableCalendar())
    }

    @Test
    fun `inactive Google Calendar cannot write`() {
        assertFalse(row(IntegrationProvider.GOOGLE_CALENDAR, IntegrationStatus.EXPIRED).canWriteCalendar)
    }

    @Test
    fun `Outlook with Calendars ReadWrite can write, matched case-insensitively`() {
        assertTrue(row(IntegrationProvider.OUTLOOK, scopes = listOf("Mail.Read", graphCalendarScope)).canWriteCalendar)
        assertTrue(row(IntegrationProvider.OUTLOOK, scopes = listOf("calendars.readwrite")).canWriteCalendar)
        assertTrue(row(IntegrationProvider.OUTLOOK, scopes = listOf("CALENDARS.READWRITE")).canWriteCalendar)
    }

    @Test
    fun `Outlook without the calendar scope cannot write`() {
        assertFalse(row(IntegrationProvider.OUTLOOK, scopes = listOf("Mail.Read", "offline_access")).canWriteCalendar)
        assertFalse(row(IntegrationProvider.OUTLOOK, scopes = null).canWriteCalendar)
        // Calendars.Read is not write access, and a prefix match is not a suffix match.
        assertFalse(row(IntegrationProvider.OUTLOOK, scopes = listOf("Calendars.Read")).canWriteCalendar)
        assertFalse(row(IntegrationProvider.OUTLOOK, scopes = listOf("Calendars.ReadWrite.Shared")).canWriteCalendar)
    }

    @Test
    fun `inactive Outlook with the calendar scope cannot write`() {
        assertFalse(
            row(IntegrationProvider.OUTLOOK, IntegrationStatus.EXPIRED, listOf(graphCalendarScope)).canWriteCalendar
        )
    }

    @Test
    fun `Gmail never writes calendars even with a calendar-looking scope`() {
        assertFalse(row(IntegrationProvider.GMAIL, scopes = listOf("calendars.readwrite")).canWriteCalendar)
        assertFalse(listOf(row(IntegrationProvider.GMAIL)).hasWritableCalendar())
    }

    @Test
    fun `scoped Outlook alone is a writable calendar`() {
        assertTrue(
            listOf(
                row(IntegrationProvider.OUTLOOK, scopes = listOf(graphCalendarScope))
            ).hasWritableCalendar()
        )
    }

    @Test
    fun `needsOutlookCalendarReconnect only for active Outlook missing the scope`() {
        assertTrue(listOf(row(IntegrationProvider.OUTLOOK, scopes = listOf("Mail.Read"))).needsOutlookCalendarReconnect())
        assertFalse(
            listOf(row(IntegrationProvider.OUTLOOK, scopes = listOf(graphCalendarScope))).needsOutlookCalendarReconnect()
        )
        // An expired Outlook row is a plain reconnect, surfaced elsewhere.
        assertFalse(
            listOf(row(IntegrationProvider.OUTLOOK, IntegrationStatus.EXPIRED)).needsOutlookCalendarReconnect()
        )
        assertFalse(listOf(row(IntegrationProvider.GMAIL)).needsOutlookCalendarReconnect())
        assertFalse(emptyList<Integration>().needsOutlookCalendarReconnect())
    }

    @Test
    fun `null scopes in the row decode instead of failing the list`() {
        val json = Json { ignoreUnknownKeys = true }
        val decoded = json.decodeFromString<Integration>(
            """{"id":"i","user_id":"u","provider":"outlook","status":"active","scopes":null}"""
        )
        assertNull(decoded.scopes)
        assertFalse(decoded.canWriteCalendar)

        val scoped = json.decodeFromString<Integration>(
            """{"id":"i","user_id":"u","provider":"outlook","status":"active","scopes":["$graphCalendarScope"]}"""
        )
        assertTrue(scoped.canWriteCalendar)
    }
}
