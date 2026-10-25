package net.melisma.selko.data.model

/**
 * The single Google connection behind the `gmail` and `google_calendar` rows.
 *
 * One Google consent connects both products and the callback stores the shared
 * token in both rows, so they connect, expire and disconnect together. The
 * client shows them as one card whose state derives from both rows.
 */
data class GoogleConnection(val state: State, val rows: List<Integration>) {
    sealed interface State {
        data object NotConnected : State
        data object Connected : State

        /**
         * One product is active and the other has no row: the user unticked its
         * scope on Google's consent screen.
         */
        data class Partial(val missing: IntegrationProvider) : State

        /** A row exists but is expired, revoked or errored. */
        data class NeedsReconnect(val status: IntegrationStatus) : State
    }

    val email: String? get() = rows.firstNotNullOfOrNull { it.providerEmail }

    companion object {
        val PROVIDERS = listOf(IntegrationProvider.GMAIL, IntegrationProvider.GOOGLE_CALENDAR)

        fun from(integrations: List<Integration>): GoogleConnection {
            val gmail = integrations.find { it.provider == IntegrationProvider.GMAIL }
            val calendar = integrations.find { it.provider == IntegrationProvider.GOOGLE_CALENDAR }
            val rows = listOfNotNull(gmail, calendar)
            val inactive = rows.firstOrNull { it.status != IntegrationStatus.ACTIVE }
            val state = when {
                rows.isEmpty() -> State.NotConnected
                inactive != null -> State.NeedsReconnect(inactive.status)
                gmail != null && calendar != null -> State.Connected
                else -> State.Partial(
                    missing = if (gmail == null) IntegrationProvider.GMAIL else IntegrationProvider.GOOGLE_CALENDAR
                )
            }
            return GoogleConnection(state, rows)
        }
    }
}
