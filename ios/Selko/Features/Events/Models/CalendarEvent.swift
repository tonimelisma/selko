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
    case cancelQueued = "cancel_queued"
    case cancelled
    case rejected
}

enum EventReviewStatus: String, Codable, Sendable {
    case pendingReview = "pending_review"
    case active
    case rejected
    case cancelled
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
    let reviewStatus: EventReviewStatus?
    let googleCalendarEventId: String?
    let syncedAt: Date?
    let createdAt: Date?
    let updatedAt: Date?
    let eventSources: [EventSource]?
    let eventChangeProposals: [EventChangeProposal]?
    let calendarWorkItems: [CalendarWorkItem]?

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
        case reviewStatus = "review_status"
        case googleCalendarEventId = "google_calendar_event_id"
        case syncedAt = "synced_at"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case eventSources = "event_sources"
        case eventChangeProposals = "event_change_proposals"
        case calendarWorkItems = "calendar_work_items"
    }

    init(
        id: UUID,
        userId: UUID,
        title: String,
        startDatetime: Date?,
        endDatetime: Date?,
        allDay: Bool,
        location: String?,
        description: String?,
        sourceAttribution: String?,
        status: EventStatus,
        reviewStatus: EventReviewStatus? = nil,
        googleCalendarEventId: String?,
        syncedAt: Date?,
        createdAt: Date?,
        updatedAt: Date?,
        eventSources: [EventSource]?,
        eventChangeProposals: [EventChangeProposal]? = nil,
        calendarWorkItems: [CalendarWorkItem]? = nil
    ) {
        self.id = id
        self.userId = userId
        self.title = title
        self.startDatetime = startDatetime
        self.endDatetime = endDatetime
        self.allDay = allDay
        self.location = location
        self.description = description
        self.sourceAttribution = sourceAttribution
        self.status = status
        self.reviewStatus = reviewStatus
        self.googleCalendarEventId = googleCalendarEventId
        self.syncedAt = syncedAt
        self.createdAt = createdAt
        self.updatedAt = updatedAt
        self.eventSources = eventSources
        self.eventChangeProposals = eventChangeProposals
        self.calendarWorkItems = calendarWorkItems
    }

    var isPending: Bool {
        isNewReview || isPendingChange
    }

    var isPendingChange: Bool {
        eventChangeProposals?.contains { $0.status == .pending } == true
            || (eventChangeProposals == nil && status == .pendingChange)
    }

    var isNewReview: Bool {
        reviewStatus == .pendingReview || (reviewStatus == nil && status == .pendingReview)
    }

    var hasAppliedProposal: Bool {
        eventChangeProposals?.contains { $0.status == .applied } == true
    }

    var hasClosedLegacyProposal: Bool {
        eventChangeProposals?.contains { $0.status == .closedLegacy } == true
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
