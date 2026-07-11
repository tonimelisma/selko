//
//  CalendarEvent.swift
//  Selko
//

import Foundation

enum EventStatus: String, Codable, Sendable {
    case pendingReview = "pending_review"
    case pendingChange = "pending_change"
    case approved
    case syncing
    case synced
    case syncFailed = "sync_failed"
    case cancelled
    case rejected
}

struct CalendarEvent: Identifiable, Codable, Sendable, Equatable {
    let id: UUID
    let userId: UUID
    let title: String
    let startDatetime: Date?
    let endDatetime: Date?
    let allDay: Bool
    let location: String?
    let description: String?
    let sourceAttribution: String?
    let status: EventStatus
    let googleCalendarEventId: String?
    let syncedAt: Date?
    let createdAt: Date?
    let updatedAt: Date?
    let eventSources: [EventSource]?

    enum CodingKeys: String, CodingKey {
        case id
        case userId = "user_id"
        case title
        case startDatetime = "start_datetime"
        case endDatetime = "end_datetime"
        case allDay = "all_day"
        case location
        case description
        case sourceAttribution = "source_attribution"
        case status
        case googleCalendarEventId = "google_calendar_event_id"
        case syncedAt = "synced_at"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case eventSources = "event_sources"
    }

    var isPending: Bool {
        status == .pendingReview || status == .pendingChange
    }

    var isPendingChange: Bool {
        status == .pendingChange
    }

    var isSynced: Bool {
        status == .synced
    }
}

extension CalendarEvent {
    static var mock: CalendarEvent {
        CalendarEvent(
            id: UUID(),
            userId: UUID(),
            title: "Test Event",
            startDatetime: Date().addingTimeInterval(86400),
            endDatetime: Date().addingTimeInterval(90000),
            allDay: false,
            location: "Conference Room",
            description: "A test event",
            sourceAttribution: "From test@example.com",
            status: .pendingReview,
            googleCalendarEventId: nil,
            syncedAt: nil,
            createdAt: Date(),
            updatedAt: Date(),
            eventSources: nil
        )
    }
}
