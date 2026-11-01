package net.melisma.selko.data.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlin.time.Instant

@Serializable
enum class IntegrationProvider {
    @SerialName("gmail") GMAIL,
    @SerialName("outlook") OUTLOOK,
    @SerialName("google_photos") GOOGLE_PHOTOS,
    @SerialName("google_calendar") GOOGLE_CALENDAR
}

@Serializable
enum class IntegrationStatus {
    @SerialName("active") ACTIVE,
    @SerialName("expired") EXPIRED,
    @SerialName("revoked") REVOKED,
    @SerialName("error") ERROR
}

@Serializable
enum class IntegrationRecoveryStatus {
    @SerialName("pending") PENDING,
    @SerialName("processing") PROCESSING,
    @SerialName("waiting") WAITING,
    @SerialName("completed") COMPLETED,
    @SerialName("completed_with_errors") COMPLETED_WITH_ERRORS,
    @SerialName("failed") FAILED,
    @SerialName("superseded") SUPERSEDED
}

@Serializable
data class IntegrationRecovery(
    val id: String,
    @SerialName("integration_id") val integrationId: String,
    @SerialName("user_id") val userId: String,
    val provider: IntegrationProvider,
    val status: IntegrationRecoveryStatus,
    @SerialName("discovered_count") val discoveredCount: Int? = null,
    @SerialName("completed_count") val completedCount: Int? = null,
    @SerialName("remaining_count") val remainingCount: Int? = null,
    @SerialName("error_detail") val errorDetail: String? = null,
    @SerialName("requested_at") val requestedAt: Instant? = null
) {
    val isActive: Boolean
        get() = status == IntegrationRecoveryStatus.PENDING ||
            status == IntegrationRecoveryStatus.PROCESSING ||
            status == IntegrationRecoveryStatus.WAITING

    val needingAttentionCount: Int
        get() = maxOf(0, (discoveredCount ?: 0) - (completedCount ?: 0))
}

@Serializable
data class Integration(
    val id: String,
    @SerialName("user_id") val userId: String,
    val provider: IntegrationProvider,
    val status: IntegrationStatus,
    @SerialName("provider_email") val providerEmail: String? = null,
    // Nullable: the column is a nullable text[] and a JSON null must not
    // fail decoding of the whole integrations list.
    val scopes: List<String>? = null,
    @SerialName("last_sync_at") val lastSyncAt: Instant? = null,
    @SerialName("created_at") val createdAt: Instant? = null,
    @SerialName("updated_at") val updatedAt: Instant? = null
) {
    val isActive: Boolean
        get() = status == IntegrationStatus.ACTIVE

    /** True when the Outlook token was granted Microsoft Graph `Calendars.ReadWrite`. */
    val hasOutlookCalendarScope: Boolean
        get() = provider == IntegrationProvider.OUTLOOK &&
            scopes.orEmpty().any { it.lowercase().endsWith(OUTLOOK_CALENDAR_SCOPE_SUFFIX) }

    /**
     * Whether Selko can write events to a calendar through this row: an active
     * Google Calendar row, or an active Outlook row that carries the calendar scope.
     * The Outlook row is shared with Outlook mail, so `active` alone is not enough.
     */
    val canWriteCalendar: Boolean
        get() = isActive && when (provider) {
            IntegrationProvider.GOOGLE_CALENDAR -> true
            IntegrationProvider.OUTLOOK -> hasOutlookCalendarScope
            else -> false
        }

    companion object {
        const val OUTLOOK_CALENDAR_SCOPE_SUFFIX = "calendars.readwrite"
    }
}

/** At least one integration can receive event writes (Google Calendar or Outlook Calendar). */
fun List<Integration>.hasWritableCalendar(): Boolean = any { it.canWriteCalendar }

/**
 * An active Outlook connection that predates the calendar scope. Outlook mail
 * keeps working; reconnecting Outlook grants `Calendars.ReadWrite` so Outlook
 * calendars become selectable. True even when Google Calendar is writable.
 */
fun List<Integration>.needsOutlookCalendarReconnect(): Boolean =
    any { it.provider == IntegrationProvider.OUTLOOK && it.isActive && !it.hasOutlookCalendarScope }
