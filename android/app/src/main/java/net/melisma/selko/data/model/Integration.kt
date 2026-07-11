package net.melisma.selko.data.model

import kotlinx.datetime.Instant
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

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
