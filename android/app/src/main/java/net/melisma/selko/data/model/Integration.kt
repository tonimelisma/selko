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
    val scopes: List<String> = emptyList(),
    @SerialName("last_sync_at") val lastSyncAt: Instant? = null,
    @SerialName("created_at") val createdAt: Instant? = null,
    @SerialName("updated_at") val updatedAt: Instant? = null
) {
    val isActive: Boolean
        get() = status == IntegrationStatus.ACTIVE
}
