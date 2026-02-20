//
//  MockEventService.swift
//  SelkoTests
//

import Foundation
@testable import iOS

final class MockEventService: EventServiceProtocol, @unchecked Sendable {
    var fetchPendingEventsResult: Result<[CalendarEvent], Error> = .success([])
    var fetchPendingEventsWithSourcesResult: Result<[CalendarEvent], Error> = .success([])
    var approveEventResult: Result<CalendarEvent, Error> = .success(.mock)
    var rejectEventResult: Result<CalendarEvent, Error> = .success(.mock)

    var approveEventCallCount = 0
    var rejectEventCallCount = 0
    var lastApprovedEventId: UUID?
    var lastRejectedEventId: UUID?

    func fetchPendingEvents() async throws -> [CalendarEvent] {
        switch fetchPendingEventsResult {
        case .success(let events): return events
        case .failure(let error): throw error
        }
    }

    func fetchPendingEventsWithSources() async throws -> [CalendarEvent] {
        switch fetchPendingEventsWithSourcesResult {
        case .success(let events): return events
        case .failure(let error): throw error
        }
    }

    func fetchActivityEvents(limit: Int, offset: Int) async throws -> [CalendarEvent] {
        return []
    }

    func fetchEvents(limit: Int, offset: Int, statuses: [EventStatus]?, startAfter: Date?, startBefore: Date?) async throws -> [CalendarEvent] {
        return []
    }

    func getEvent(id: UUID) async throws -> CalendarEvent {
        return .mock
    }

    func getEventWithSources(id: UUID) async throws -> CalendarEvent {
        return .mock
    }

    func updateEventStatus(id: UUID, status: EventStatus) async throws -> CalendarEvent {
        return .mock
    }

    func updateEvent(id: UUID, title: String?, startDatetime: Date?, endDatetime: Date?, allDay: Bool?, location: String?, description: String?) async throws -> CalendarEvent {
        return .mock
    }

    func approveEvent(id: UUID) async throws -> CalendarEvent {
        approveEventCallCount += 1
        lastApprovedEventId = id
        switch approveEventResult {
        case .success(let event): return event
        case .failure(let error): throw error
        }
    }

    func rejectEvent(id: UUID) async throws -> CalendarEvent {
        rejectEventCallCount += 1
        lastRejectedEventId = id
        switch rejectEventResult {
        case .success(let event): return event
        case .failure(let error): throw error
        }
    }
}
