package net.melisma.selko.data.model

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class GoogleConnectionTest {

    private fun row(provider: IntegrationProvider, status: IntegrationStatus = IntegrationStatus.ACTIVE) =
        Integration(
            id = provider.name,
            userId = "user-1",
            provider = provider,
            status = status,
            providerEmail = "user@gmail.com"
        )

    @Test
    fun `no Google rows is not connected even with Outlook`() {
        val google = GoogleConnection.from(listOf(row(IntegrationProvider.OUTLOOK)))
        assertEquals(GoogleConnection.State.NotConnected, google.state)
        assertTrue(google.rows.isEmpty())
    }

    @Test
    fun `both active rows are connected`() {
        val google = GoogleConnection.from(
            listOf(row(IntegrationProvider.GMAIL), row(IntegrationProvider.GOOGLE_CALENDAR))
        )
        assertEquals(GoogleConnection.State.Connected, google.state)
        assertEquals("user@gmail.com", google.email)
    }

    @Test
    fun `one active row names the missing product`() {
        assertEquals(
            GoogleConnection.State.Partial(IntegrationProvider.GOOGLE_CALENDAR),
            GoogleConnection.from(listOf(row(IntegrationProvider.GMAIL))).state
        )
        assertEquals(
            GoogleConnection.State.Partial(IntegrationProvider.GMAIL),
            GoogleConnection.from(listOf(row(IntegrationProvider.GOOGLE_CALENDAR))).state
        )
    }

    @Test
    fun `any inactive row needs reconnect`() {
        assertEquals(
            GoogleConnection.State.NeedsReconnect(IntegrationStatus.EXPIRED),
            GoogleConnection.from(
                listOf(
                    row(IntegrationProvider.GMAIL),
                    row(IntegrationProvider.GOOGLE_CALENDAR, IntegrationStatus.EXPIRED)
                )
            ).state
        )
        assertEquals(
            GoogleConnection.State.NeedsReconnect(IntegrationStatus.REVOKED),
            GoogleConnection.from(listOf(row(IntegrationProvider.GMAIL, IntegrationStatus.REVOKED))).state
        )
    }
}
