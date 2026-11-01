package net.melisma.selko.ui.screens.review

import net.melisma.selko.data.model.Integration
import net.melisma.selko.data.model.IntegrationProvider
import net.melisma.selko.data.model.IntegrationStatus
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Approval gating and recovery prompts treat a calendar-scoped Outlook like Google Calendar. */
class CalendarGatingTest {

    private val calendarScope = "https://graph.microsoft.com/Calendars.ReadWrite"

    private fun row(
        provider: IntegrationProvider,
        status: IntegrationStatus = IntegrationStatus.ACTIVE,
        scopes: List<String>? = null
    ) = Integration(id = provider.name, userId = "user-1", provider = provider, status = status, scopes = scopes)

    private val scopedOutlook = row(IntegrationProvider.OUTLOOK, scopes = listOf("Mail.Read", calendarScope))
    private val mailOnlyOutlook = row(IntegrationProvider.OUTLOOK, scopes = listOf("Mail.Read"))

    @Test
    fun `review queue can approve with only a calendar-scoped Outlook`() {
        val state = ReviewQueueUiState(integrations = listOf(scopedOutlook))
        assertTrue(state.isEmailConnected)
        assertTrue(state.isCalendarConnected)
    }

    @Test
    fun `review queue cannot approve with mail-only Outlook`() {
        assertFalse(ReviewQueueUiState(integrations = listOf(mailOnlyOutlook)).isCalendarConnected)
    }

    @Test
    fun `review queue still approves with Google Calendar`() {
        assertTrue(
            ReviewQueueUiState(
                integrations = listOf(row(IntegrationProvider.GMAIL), row(IntegrationProvider.GOOGLE_CALENDAR))
            ).isCalendarConnected
        )
    }

    @Test
    fun `event detail gating follows the same rule`() {
        assertTrue(EventDetailUiState(integrations = listOf(scopedOutlook)).isCalendarConnected)
        assertFalse(EventDetailUiState(integrations = listOf(mailOnlyOutlook)).isCalendarConnected)
        assertFalse(
            EventDetailUiState(
                integrations = listOf(row(IntegrationProvider.GOOGLE_CALENDAR, IntegrationStatus.EXPIRED))
            ).isCalendarConnected
        )
    }

    @Test
    fun `scoped Outlook alone needs no recovery prompt`() {
        assertEquals(emptyList<IntegrationProvider>(), recoveryProvidersFor(listOf(scopedOutlook)))
    }

    @Test
    fun `stale Google Calendar is not prompted when Outlook calendar is writable`() {
        val integrations = listOf(
            scopedOutlook,
            row(IntegrationProvider.GOOGLE_CALENDAR, IntegrationStatus.EXPIRED)
        )
        assertEquals(emptyList<IntegrationProvider>(), recoveryProvidersFor(integrations))
    }

    @Test
    fun `stale Gmail is still prompted when Outlook calendar is writable`() {
        val integrations = listOf(scopedOutlook, row(IntegrationProvider.GMAIL, IntegrationStatus.EXPIRED))
        assertEquals(listOf(IntegrationProvider.GMAIL), recoveryProvidersFor(integrations))
    }

    @Test
    fun `mail-only Outlook offers an Outlook reconnect before Google Calendar`() {
        assertEquals(
            listOf(IntegrationProvider.OUTLOOK, IntegrationProvider.GOOGLE_CALENDAR),
            recoveryProvidersFor(listOf(mailOnlyOutlook))
        )
    }

    @Test
    fun `Gmail without a calendar still prompts Google Calendar only`() {
        assertEquals(
            listOf(IntegrationProvider.GOOGLE_CALENDAR),
            recoveryProvidersFor(listOf(row(IntegrationProvider.GMAIL)))
        )
    }
}
