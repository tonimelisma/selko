package net.melisma.selko.data.repository

import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.postgrest.from
import io.github.jan.supabase.postgrest.postgrest
import io.github.jan.supabase.postgrest.rpc
import io.github.jan.supabase.postgrest.query.Columns
import io.github.jan.supabase.postgrest.query.Order
import io.github.jan.supabase.postgrest.query.filter.FilterOperator
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import net.melisma.selko.data.model.CalendarEvent
import net.melisma.selko.data.model.EventStatus
import kotlin.time.Instant

sealed class EventResult<out T> {
    data class Success<T>(val data: T) : EventResult<T>()
    data class Error(val message: String) : EventResult<Nothing>()
}

data class FetchEventsOptions(
    val limit: Int = 50,
    val offset: Int = 0,
    val statuses: List<EventStatus>? = null,
    val startAfter: Instant? = null,
    val startBefore: Instant? = null
)

class EventRepository(
    private val supabaseClient: SupabaseClient
) {
    suspend fun fetchPendingEvents(): EventResult<List<CalendarEvent>> {
        return try {
            val now = kotlin.time.Clock.System.now()
            val nowStr = now.toString()
            val events = supabaseClient.from("events")
                .select {
                    filter {
                        isIn("review_status", listOf("pending_review", "active"))
                        or {
                            gte("end_datetime", nowStr)
                            gte("start_datetime", nowStr)
                        }
                    }
                    order("start_datetime", Order.ASCENDING)
                }
                .decodeList<CalendarEvent>()

            val filtered = events.filter { event ->
                val effective = event.endDatetime ?: event.startDatetime ?: return@filter true
                effective >= now
            }
            EventResult.Success(filtered)
        } catch (e: Exception) {
            EventResult.Error(e.message ?: "Failed to fetch pending events")
        }
    }

    suspend fun fetchEvents(options: FetchEventsOptions = FetchEventsOptions()): EventResult<List<CalendarEvent>> {
        return try {
            val events = supabaseClient.from("events")
                .select {
                    filter {
                        options.statuses?.let { statuses ->
                            if (statuses.isNotEmpty()) {
                                val reviewStatuses = statuses.mapNotNull {
                                    when (it) {
                                        EventStatus.PENDING_REVIEW -> "pending_review"
                                        EventStatus.REJECTED -> "rejected"
                                        EventStatus.CANCELLED -> "cancelled"
                                        else -> null
                                    }
                                }
                                if (reviewStatuses.size == statuses.size) {
                                    isIn("review_status", reviewStatuses)
                                }
                            }
                        }
                        options.startAfter?.let {
                            gte("start_datetime", it.toString())
                        }
                        options.startBefore?.let {
                            lte("start_datetime", it.toString())
                        }
                    }
                    order("start_datetime", Order.ASCENDING)
                    range(options.offset.toLong(), (options.offset + options.limit - 1).toLong())
                }
                .decodeList<CalendarEvent>()

            EventResult.Success(events)
        } catch (e: Exception) {
            EventResult.Error(e.message ?: "Failed to fetch events")
        }
    }

    suspend fun getEvent(eventId: String): EventResult<CalendarEvent> {
        return try {
            val event = supabaseClient.from("events")
                .select {
                    filter {
                        eq("id", eventId)
                    }
                }
                .decodeSingle<CalendarEvent>()

            EventResult.Success(event)
        } catch (e: Exception) {
            EventResult.Error(e.message ?: "Failed to fetch event")
        }
    }

    suspend fun getEventWithSources(eventId: String): EventResult<CalendarEvent> {
        return try {
            val event = supabaseClient.from("events")
                .select(Columns.raw("*, event_sources(*, emails(id, subject, from_email, from_name, date_sent)), event_change_proposals(id, event_id, user_id, source_id, kind, status, change_set, resolution_reason, created_at, resolved_at, updated_at), calendar_work_items(id, event_id, user_id, action, generation, status, provider_event_id, expected_provider_revision, force_overwrite, attempts, max_attempts, next_retry_at, failure_code, failure_detail, created_at, updated_at, completed_at)")) {
                    filter {
                        eq("id", eventId)
                    }
                }
                .decodeSingle<CalendarEvent>()

            EventResult.Success(event)
        } catch (e: Exception) {
            EventResult.Error(e.message ?: "Failed to fetch event with sources")
        }
    }

    suspend fun updateEventStatus(eventId: String, status: EventStatus): EventResult<CalendarEvent> {
        return try {
            val reviewStatus = when (status) {
                EventStatus.APPROVED -> "active"
                EventStatus.REJECTED -> "rejected"
                else -> throw IllegalArgumentException("Unsupported review transition: $status")
            }
            supabaseClient.postgrest.rpc("set_event_review_status", buildJsonObject {
                put("p_event_id", eventId)
                put("p_review_status", reviewStatus)
            })
            val event = getEventWithSources(eventId).let { result ->
                when (result) {
                    is EventResult.Success -> result.data
                    is EventResult.Error -> throw IllegalStateException(result.message)
                }
            }

            EventResult.Success(event)
        } catch (e: Exception) {
            EventResult.Error(e.message ?: "Failed to update event status")
        }
    }

    suspend fun updateEvent(
        eventId: String,
        title: String? = null,
        startDatetime: Instant? = null,
        endDatetime: Instant? = null,
        allDay: Boolean? = null,
        location: String? = null,
        description: String? = null
    ): EventResult<CalendarEvent> {
        return try {
            val updates = mutableMapOf<String, Any?>()
            title?.let { updates["title"] = it }
            startDatetime?.let { updates["start_datetime"] = it.toString() }
            endDatetime?.let { updates["end_datetime"] = it.toString() }
            allDay?.let { updates["all_day"] = it }
            location?.let { updates["location"] = it }
            description?.let { updates["description"] = it }

            val event = supabaseClient.from("events")
                .update(updates) {
                    select()
                    filter {
                        eq("id", eventId)
                    }
                }
                .decodeSingle<CalendarEvent>()

            EventResult.Success(event)
        } catch (e: Exception) {
            EventResult.Error(e.message ?: "Failed to update event")
        }
    }

    suspend fun fetchPendingEventsWithSources(): EventResult<List<CalendarEvent>> {
        return try {
            val now = kotlin.time.Clock.System.now()
            val nowStr = now.toString()
            val events = supabaseClient.from("events")
                .select(Columns.raw("*, event_sources(*, emails(id, subject, from_email, from_name, date_sent)), event_change_proposals(id, event_id, user_id, source_id, kind, status, change_set, resolution_reason, created_at, resolved_at, updated_at), calendar_work_items(id, event_id, user_id, action, generation, status, provider_event_id, expected_provider_revision, force_overwrite, attempts, max_attempts, next_retry_at, failure_code, failure_detail, created_at, updated_at, completed_at)")) {
                    filter {
                        isIn("review_status", listOf("pending_review", "active"))
                        or {
                            gte("end_datetime", nowStr)
                            gte("start_datetime", nowStr)
                        }
                    }
                    order("start_datetime", Order.ASCENDING)
                }
                .decodeList<CalendarEvent>()
            val filtered = events.filter { event ->
                val effective = event.endDatetime ?: event.startDatetime ?: return@filter true
                effective >= now
            }
            EventResult.Success(filtered.filter { it.isPending })
        } catch (e: Exception) {
            EventResult.Error(e.message ?: "Failed to fetch pending events with sources")
        }
    }

    suspend fun fetchActivityEvents(limit: Int = 20, offset: Int = 0): EventResult<List<CalendarEvent>> {
        return try {
            val events = supabaseClient.from("events")
                .select(Columns.raw("*, event_sources(*, emails(id, subject, from_email, from_name, date_sent)), event_change_proposals(id, event_id, user_id, source_id, kind, status, change_set, resolution_reason, created_at, resolved_at, updated_at), calendar_work_items(id, event_id, user_id, action, generation, status, provider_event_id, expected_provider_revision, force_overwrite, attempts, max_attempts, next_retry_at, failure_code, failure_detail, created_at, updated_at, completed_at)")) {
                    filter {
                        isIn("review_status", listOf("active", "rejected", "cancelled"))
                        filterNot("event_change_proposals.status", FilterOperator.EQ, "pending")
                    }
                    order("updated_at", Order.DESCENDING)
                    range(offset.toLong(), (offset + limit - 1).toLong())
                }
                .decodeList<CalendarEvent>()
            EventResult.Success(events.filter { !it.isPendingChange })
        } catch (e: Exception) {
            EventResult.Error(e.message ?: "Failed to fetch activity events")
        }
    }

    suspend fun approveEvent(eventId: String): EventResult<CalendarEvent> =
        updateEventStatus(eventId, EventStatus.APPROVED)

    suspend fun rejectEvent(eventId: String): EventResult<CalendarEvent> =
        updateEventStatus(eventId, EventStatus.REJECTED)
}
