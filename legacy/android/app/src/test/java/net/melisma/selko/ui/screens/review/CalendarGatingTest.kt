package net.melisma.selko.ui.screens.review

import net.melisma.selko.data.model.Integration
import net.melisma.selko.data.model.IntegrationProvider
import net.melisma.selko.data.model.IntegrationStatus
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
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

    private fun actions(integrations: List<Integration>) = recoveryPlanFor(integrations)?.actions.orEmpty()

    @Test
    fun `Google signed out beside mail-only Outlook names Google only`() {
        // Regression: production showed "Reconnect your calendar" with equal
        // Outlook and Google buttons, although Gmail was down too and Outlook
        // had never been the user's calendar.
        val plan = recoveryPlanFor(
            listOf(
                row(IntegrationProvider.GMAIL, IntegrationStatus.EXPIRED),
                row(IntegrationProvider.GOOGLE_CALENDAR, IntegrationStatus.EXPIRED),
                mailOnlyOutlook
            )
        )
        assertEquals(
            RecoveryKind.SignedOut(RecoverySignIn.GOOGLE, LostAccess.MAIL_AND_CALENDAR),
            plan?.kind
        )
        assertEquals(listOf(RecoveryAction(RecoverySignIn.GOOGLE, RecoveryVerb.RECONNECT)), plan?.actions)
        assertEquals(IntegrationProvider.GMAIL, plan?.actions?.single()?.authProvider)
    }

    @Test
    fun `scoped Outlook alone needs no prompt`() {
        assertNull(recoveryPlanFor(listOf(scopedOutlook)))
    }

    @Test
    fun `stale Google Calendar is quiet while Outlook calendar is writable`() {
        assertNull(
            recoveryPlanFor(listOf(scopedOutlook, row(IntegrationProvider.GOOGLE_CALENDAR, IntegrationStatus.EXPIRED)))
        )
    }

    @Test
    fun `stale Gmail beside a writable Outlook calendar says mail only`() {
        val plan = recoveryPlanFor(listOf(scopedOutlook, row(IntegrationProvider.GMAIL, IntegrationStatus.EXPIRED)))
        assertEquals(RecoveryKind.SignedOut(RecoverySignIn.GOOGLE, LostAccess.MAIL), plan?.kind)
    }

    @Test
    fun `lapsed Google Calendar alone says calendar`() {
        val plan = recoveryPlanFor(
            listOf(row(IntegrationProvider.GMAIL), row(IntegrationProvider.GOOGLE_CALENDAR, IntegrationStatus.REVOKED))
        )
        assertEquals(RecoveryKind.SignedOut(RecoverySignIn.GOOGLE, LostAccess.CALENDAR), plan?.kind)
        assertEquals(1, plan?.actions?.size)
    }

    @Test
    fun `mail-only Outlook offers Outlook Calendar only`() {
        assertEquals(RecoveryKind.ConnectCalendar, recoveryPlanFor(listOf(mailOnlyOutlook))?.kind)
        assertEquals(
            listOf(RecoveryAction(RecoverySignIn.OUTLOOK, RecoveryVerb.CONNECT_CALENDAR)),
            actions(listOf(mailOnlyOutlook))
        )
    }

    @Test
    fun `Gmail without a calendar offers Google Calendar`() {
        assertEquals(
            listOf(RecoveryAction(RecoverySignIn.GOOGLE, RecoveryVerb.CONNECT_CALENDAR)),
            actions(listOf(row(IntegrationProvider.GMAIL)))
        )
    }

    @Test
    fun `both sign-ins lapsed offer both`() {
        val plan = recoveryPlanFor(
            listOf(
                row(IntegrationProvider.GMAIL, IntegrationStatus.EXPIRED),
                row(IntegrationProvider.OUTLOOK, IntegrationStatus.EXPIRED)
            )
        )
        assertEquals(RecoveryKind.Accounts, plan?.kind)
        assertEquals(listOf(RecoverySignIn.GOOGLE, RecoverySignIn.OUTLOOK), plan?.actions?.map { it.signIn })
    }
}
