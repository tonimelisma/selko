package net.melisma.selko.data.model

import kotlinx.datetime.Instant
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
enum class EventStatus {
    @SerialName("pending_review") PENDING_REVIEW,
    @SerialName("approved") APPROVED,
    @SerialName("syncing") SYNCING,
    @SerialName("synced") SYNCED,
    @SerialName("sync_failed") SYNC_FAILED,
    @SerialName("cancelled") CANCELLED,
    @SerialName("rejected") REJECTED
}

@Serializable
data class CalendarEvent(
    val id: String,
    @SerialName("user_id") val userId: String,
    val title: String,
    @SerialName("start_datetime") val startDatetime: Instant? = null,
    @SerialName("end_datetime") val endDatetime: Instant? = null,
    @SerialName("all_day") val allDay: Boolean = false,
    val location: String? = null,
    val description: String? = null,
    @SerialName("source_attribution") val sourceAttribution: String? = null,
    val status: EventStatus = EventStatus.PENDING_REVIEW,
    @SerialName("google_calendar_event_id") val googleCalendarEventId: String? = null,
    @SerialName("synced_at") val syncedAt: Instant? = null,
    @SerialName("created_at") val createdAt: Instant? = null,
    @SerialName("updated_at") val updatedAt: Instant? = null,
    // Joined data when fetching with sources
    @SerialName("event_sources") val eventSources: List<EventSource>? = null
) {
    val isPending: Boolean
        get() = status == EventStatus.PENDING_REVIEW

    val isSynced: Boolean
        get() = status == EventStatus.SYNCED
}
