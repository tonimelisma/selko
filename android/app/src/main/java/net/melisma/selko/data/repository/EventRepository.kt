package net.melisma.selko.data.repository

import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.postgrest.from
import io.github.jan.supabase.postgrest.query.Columns
import io.github.jan.supabase.postgrest.query.Order
import kotlinx.datetime.Instant
import net.melisma.selko.data.model.CalendarEvent
import net.melisma.selko.data.model.EventStatus

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
    private fun statusToString(status: EventStatus): String = when (status) {
        EventStatus.PENDING_REVIEW -> "pending_review"
        EventStatus.PENDING_CHANGE -> "pending_change"
        EventStatus.APPROVED -> "approved"
        EventStatus.SYNCING -> "syncing"
        EventStatus.SYNCED -> "synced"
        EventStatus.SYNC_FAILED -> "sync_failed"
        EventStatus.CANCELLED -> "cancelled"
        EventStatus.REJECTED -> "rejected"
    }

    suspend fun fetchPendingEvents(): EventResult<List<CalendarEvent>> {
        return try {
            val events = supabaseClient.from("events")
                .select {
                    filter {
                        isIn("status", listOf("pending_review", "pending_change"))
                    }
                    order("start_datetime", Order.ASCENDING)
                }
                .decodeList<CalendarEvent>()

            EventResult.Success(events)
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
                                isIn("status", statuses.map { statusToString(it) })
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
                .select(Columns.raw("*, event_sources(*, emails(id, subject, from_email, from_name, date_sent))")) {
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
            val event = supabaseClient.from("events")
                .update(mapOf("status" to statusToString(status))) {
                    select()
                    filter {
                        eq("id", eventId)
                    }
                }
                .decodeSingle<CalendarEvent>()

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
            val events = supabaseClient.from("events")
                .select(Columns.raw("*, event_sources(*, emails(id, subject, from_email, from_name, date_sent))")) {
                    filter { isIn("status", listOf("pending_review", "pending_change")) }
                    order("start_datetime", Order.ASCENDING)
                }
                .decodeList<CalendarEvent>()
            EventResult.Success(events)
        } catch (e: Exception) {
            EventResult.Error(e.message ?: "Failed to fetch pending events with sources")
        }
    }

    suspend fun fetchActivityEvents(limit: Int = 20, offset: Int = 0): EventResult<List<CalendarEvent>> {
        return try {
            val events = supabaseClient.from("events")
                .select(Columns.raw("*, event_sources(*, emails(id, subject, from_email, from_name, date_sent))")) {
                    filter {
                        isIn("status", listOf("approved", "synced", "sync_failed", "rejected", "cancelled"))
                    }
                    order("updated_at", Order.DESCENDING)
                    range(offset.toLong(), (offset + limit - 1).toLong())
                }
                .decodeList<CalendarEvent>()
            EventResult.Success(events)
        } catch (e: Exception) {
            EventResult.Error(e.message ?: "Failed to fetch activity events")
        }
    }

    suspend fun approveEvent(eventId: String): EventResult<CalendarEvent> =
        updateEventStatus(eventId, EventStatus.APPROVED)

    suspend fun rejectEvent(eventId: String): EventResult<CalendarEvent> =
        updateEventStatus(eventId, EventStatus.REJECTED)
}
