package net.melisma.selko.data.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlin.time.Instant

@Serializable
enum class CalendarWorkAction {
    @SerialName("upsert") UPSERT,
    @SerialName("cancel") CANCEL
}

@Serializable
enum class CalendarWorkStatus {
    @SerialName("pending") PENDING,
    @SerialName("processing") PROCESSING,
    @SerialName("succeeded") SUCCEEDED,
    @SerialName("failed") FAILED,
    @SerialName("blocked") BLOCKED,
    @SerialName("superseded") SUPERSEDED
}

@Serializable
data class CalendarWorkItem(
    val id: String,
    @SerialName("event_id") val eventId: String,
    @SerialName("user_id") val userId: String,
    val action: CalendarWorkAction,
    val generation: Long,
    val status: CalendarWorkStatus,
    @SerialName("provider_event_id") val providerEventId: String? = null,
    @SerialName("expected_provider_revision") val expectedProviderRevision: String? = null,
    @SerialName("force_overwrite") val forceOverwrite: Boolean = false,
    val attempts: Int = 0,
    @SerialName("max_attempts") val maxAttempts: Int = 3,
    @SerialName("next_retry_at") val nextRetryAt: Instant? = null,
    @SerialName("failure_code") val failureCode: String? = null,
    @SerialName("failure_detail") val failureDetail: String? = null,
    @SerialName("created_at") val createdAt: Instant? = null,
    @SerialName("updated_at") val updatedAt: Instant? = null,
    @SerialName("completed_at") val completedAt: Instant? = null
)
