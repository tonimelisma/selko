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
        get() = reviewStatus == EventReviewStatus.PENDING_REVIEW

    val hasAppliedProposal: Boolean
        get() = eventChangeProposals?.any { it.status == EventChangeProposalStatus.APPLIED } == true

    val hasClosedLegacyProposal: Boolean
        get() = eventChangeProposals?.any { it.status == EventChangeProposalStatus.CLOSED_LEGACY } == true

    val isSynced: Boolean
        get() = status == EventStatus.SYNCED

    val status: EventStatus
        get() {
            if (reviewStatus == EventReviewStatus.PENDING_REVIEW) return EventStatus.PENDING_REVIEW
            if (reviewStatus == EventReviewStatus.REJECTED) return EventStatus.REJECTED
            if (reviewStatus == EventReviewStatus.CANCELLED) return EventStatus.CANCELLED
            val item = calendarWorkItems
                ?.filter { it.status != CalendarWorkStatus.SUPERSEDED }
                ?.maxByOrNull { it.generation }
            if (item == null) {
                return if (googleCalendarEventId == null) EventStatus.APPROVED else EventStatus.SYNCED
            }
            val oauthBlocked = item.failureCode == "oauth_required" || item.failureCode == "oauth_scope_required"
            if (item.action == CalendarWorkAction.CANCEL) {
                if (item.status == CalendarWorkStatus.SUCCEEDED) return EventStatus.CANCELLED
                if ((item.status == CalendarWorkStatus.FAILED || item.status == CalendarWorkStatus.BLOCKED) && !oauthBlocked) {
                    return EventStatus.SYNC_FAILED
                }
                return EventStatus.CANCEL_QUEUED
            }
            return when (item.status) {
                CalendarWorkStatus.PROCESSING -> EventStatus.SYNCING
                CalendarWorkStatus.SUCCEEDED -> EventStatus.SYNCED
                CalendarWorkStatus.FAILED, CalendarWorkStatus.BLOCKED -> if (oauthBlocked) EventStatus.APPROVED else EventStatus.SYNC_FAILED
                CalendarWorkStatus.PENDING, CalendarWorkStatus.SUPERSEDED -> EventStatus.APPROVED
            }
        }
}
