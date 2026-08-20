package net.melisma.selko.data.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlin.time.Instant

@Serializable
enum class EventStatus {
    @SerialName("pending_review") PENDING_REVIEW,
    @SerialName("approved") APPROVED,
    @SerialName("syncing") SYNCING,
    @SerialName("synced") SYNCED,
    @SerialName("sync_failed") SYNC_FAILED,
    @SerialName("cancel_queued") CANCEL_QUEUED,
    @SerialName("cancelled") CANCELLED,
    @SerialName("rejected") REJECTED
}

@Serializable
enum class EventReviewStatus {
    @SerialName("pending_review") PENDING_REVIEW,
    @SerialName("active") ACTIVE,
    @SerialName("rejected") REJECTED,
    @SerialName("cancelled") CANCELLED
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
    @SerialName("review_status") val reviewStatus: EventReviewStatus? = null,
    @SerialName("google_calendar_event_id") val googleCalendarEventId: String? = null,
    @SerialName("synced_at") val syncedAt: Instant? = null,
    @SerialName("created_at") val createdAt: Instant? = null,
    @SerialName("updated_at") val updatedAt: Instant? = null,
    // Joined data when fetching with sources
    @SerialName("event_sources") val eventSources: List<EventSource>? = null,
    @SerialName("event_change_proposals") val eventChangeProposals: List<EventChangeProposal>? = null,
    @SerialName("calendar_work_items") val calendarWorkItems: List<CalendarWorkItem>? = null
) {
    val isPending: Boolean
        get() = isNewReview || isPendingChange

    val isPendingChange: Boolean
        get() = eventChangeProposals?.any { it.status == EventChangeProposalStatus.PENDING } == true

    val isNewReview: Boolean
        get() = reviewStatus == EventReviewStatus.PENDING_REVIEW ||
            (reviewStatus == null && status == EventStatus.PENDING_REVIEW)

    val hasAppliedProposal: Boolean
        get() = eventChangeProposals?.any { it.status == EventChangeProposalStatus.APPLIED } == true

    val hasClosedLegacyProposal: Boolean
        get() = eventChangeProposals?.any { it.status == EventChangeProposalStatus.CLOSED_LEGACY } == true

    val isSynced: Boolean
        get() = status == EventStatus.SYNCED
}
