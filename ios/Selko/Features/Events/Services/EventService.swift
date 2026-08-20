//
//  EventService.swift
//  Selko
//

import Foundation
import Supabase

protocol EventServiceProtocol: Sendable {
    func fetchPendingEvents() async throws -> [CalendarEvent]
    func fetchPendingEventsWithSources() async throws -> [CalendarEvent]
    func fetchActivityEvents(limit: Int, offset: Int) async throws -> [CalendarEvent]
    func fetchEvents(
        limit: Int,
        offset: Int,
        statuses: [EventStatus]?,
        startAfter: Date?,
        startBefore: Date?
    ) async throws -> [CalendarEvent]
    func getEvent(id: UUID) async throws -> CalendarEvent
    func getEventWithSources(id: UUID) async throws -> CalendarEvent
    func updateEventStatus(id: UUID, status: EventStatus) async throws -> CalendarEvent
    func updateEvent(
        id: UUID,
        title: String?,
        startDatetime: Date?,
        endDatetime: Date?,
        allDay: Bool?,
        location: String?,
        description: String?
    ) async throws -> CalendarEvent
    func approveEvent(id: UUID) async throws -> CalendarEvent
    func rejectEvent(id: UUID) async throws -> CalendarEvent
}

extension EventServiceProtocol {
    func fetchEvents(
        limit: Int = 50,
        offset: Int = 0,
        statuses: [EventStatus]? = nil,
        startAfter: Date? = nil,
        startBefore: Date? = nil
    ) async throws -> [CalendarEvent] {
        try await fetchEvents(
            limit: limit,
            offset: offset,
            statuses: statuses,
            startAfter: startAfter,
            startBefore: startBefore
        )
    }

    func fetchActivityEvents(limit: Int = 20, offset: Int = 0) async throws -> [CalendarEvent] {
        try await fetchActivityEvents(limit: limit, offset: offset)
    }
}

final class EventService: EventServiceProtocol, @unchecked Sendable {
    private let supabase: SupabaseClient
    private let isoFormatter: ISO8601DateFormatter

    init(supabase: SupabaseClient) {
        self.supabase = supabase
        self.isoFormatter = ISO8601DateFormatter()
        self.isoFormatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    }

    func fetchPendingEvents() async throws -> [CalendarEvent] {
        let now = Date()
        let nowStr = isoFormatter.string(from: now)
        let orFilter = "end_datetime.gte.\(nowStr),and(end_datetime.is.null,start_datetime.gte.\(nowStr)),and(end_datetime.is.null,start_datetime.is.null)"
        let events: [CalendarEvent] = try await supabase.from("events")
            .select()
            .in("review_status", values: ["pending_review", "active"])
            .or(orFilter)
            .order("start_datetime")
            .execute()
            .value

        return events.filter { event in
            guard let effective = event.endDatetime ?? event.startDatetime else { return true }
            return effective >= now
        }
    }

    func fetchPendingEventsWithSources() async throws -> [CalendarEvent] {
        let now = Date()
        let nowStr = isoFormatter.string(from: now)
        let orFilter = "end_datetime.gte.\(nowStr),and(end_datetime.is.null,start_datetime.gte.\(nowStr)),and(end_datetime.is.null,start_datetime.is.null)"
        let events: [CalendarEvent] = try await supabase.from("events")
            .select("*, event_sources(*, emails(id, subject, from_email, from_name, date_sent)), event_change_proposals(id, event_id, user_id, source_id, kind, status, change_set, resolution_reason, created_at, resolved_at, updated_at), calendar_work_items(id, event_id, user_id, action, generation, status, provider_event_id, expected_provider_revision, force_overwrite, attempts, max_attempts, next_retry_at, failure_code, failure_detail, created_at, updated_at, completed_at)")
            .in("review_status", values: ["pending_review", "active"])
            .or(orFilter)
            .order("start_datetime")
            .execute()
            .value

        return events.filter { event in
            guard event.isPending else { return false }
            guard let effective = event.endDatetime ?? event.startDatetime else { return true }
            return effective >= now
        }
    }

    func fetchActivityEvents(limit: Int = 20, offset: Int = 0) async throws -> [CalendarEvent] {
        let events: [CalendarEvent] = try await supabase.from("events")
            .select("*, event_sources(*, emails(id, subject, from_email, from_name, date_sent)), event_change_proposals(id, event_id, user_id, source_id, kind, status, change_set, resolution_reason, created_at, resolved_at, updated_at), calendar_work_items(id, event_id, user_id, action, generation, status, provider_event_id, expected_provider_revision, force_overwrite, attempts, max_attempts, next_retry_at, failure_code, failure_detail, created_at, updated_at, completed_at)")
            .in("review_status", values: ["active", "rejected", "cancelled"])
            .order("updated_at", ascending: false)
            .range(from: offset, to: offset + limit - 1)
            .execute()
            .value

        return events.filter { !$0.isPendingChange }
    }

    func fetchEvents(
        limit: Int,
        offset: Int,
        statuses: [EventStatus]?,
        startAfter: Date?,
        startBefore: Date?
    ) async throws -> [CalendarEvent] {
        var query = supabase.from("events")
            .select()

        if let statuses = statuses, !statuses.isEmpty {
            let statusStrings = statuses.map { $0.rawValue }
            query = query.in("status", values: statusStrings)
        }

        if let startAfter = startAfter {
            query = query.gte("start_datetime", value: isoFormatter.string(from: startAfter))
        }

        if let startBefore = startBefore {
            query = query.lte("start_datetime", value: isoFormatter.string(from: startBefore))
        }

        let events: [CalendarEvent] = try await query
            .order("start_datetime")
            .range(from: offset, to: offset + limit - 1)
            .execute()
            .value

        return events
    }

    func getEvent(id: UUID) async throws -> CalendarEvent {
        let event: CalendarEvent = try await supabase.from("events")
            .select()
            .eq("id", value: id)
            .single()
            .execute()
            .value

        return event
    }

    func getEventWithSources(id: UUID) async throws -> CalendarEvent {
        let event: CalendarEvent = try await supabase.from("events")
            .select("*, event_sources(*, emails(id, subject, from_email, from_name, date_sent)), event_change_proposals(id, event_id, user_id, source_id, kind, status, change_set, resolution_reason, created_at, resolved_at, updated_at), calendar_work_items(id, event_id, user_id, action, generation, status, provider_event_id, expected_provider_revision, force_overwrite, attempts, max_attempts, next_retry_at, failure_code, failure_detail, created_at, updated_at, completed_at)")
            .eq("id", value: id)
            .single()
            .execute()
            .value

        return event
    }

    func updateEventStatus(id: UUID, status: EventStatus) async throws -> CalendarEvent {
        let event: CalendarEvent = try await supabase.from("events")
            .update(["status": status.rawValue])
            .eq("id", value: id)
            .select()
            .single()
            .execute()
            .value

        return event
    }

    func updateEvent(
        id: UUID,
        title: String?,
        startDatetime: Date?,
        endDatetime: Date?,
        allDay: Bool?,
        location: String?,
        description: String?
    ) async throws -> CalendarEvent {
        var updates: [String: AnyJSON] = [:]

        if let title = title {
            updates["title"] = .string(title)
        }
        if let startDatetime = startDatetime {
            updates["start_datetime"] = .string(isoFormatter.string(from: startDatetime))
        }
        if let endDatetime = endDatetime {
            updates["end_datetime"] = .string(isoFormatter.string(from: endDatetime))
        }
        if let allDay = allDay {
            updates["all_day"] = .bool(allDay)
        }
        if let location = location {
            updates["location"] = .string(location)
        }
        if let description = description {
            updates["description"] = .string(description)
        }

        let event: CalendarEvent = try await supabase.from("events")
            .update(updates)
            .eq("id", value: id)
            .select()
            .single()
            .execute()
            .value

        return event
    }

    func approveEvent(id: UUID) async throws -> CalendarEvent {
        try await updateEventStatus(id: id, status: .approved)
    }

    func rejectEvent(id: UUID) async throws -> CalendarEvent {
        try await updateEventStatus(id: id, status: .rejected)
    }
}
