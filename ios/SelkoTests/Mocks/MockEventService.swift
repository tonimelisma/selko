//
//  MockEventService.swift
//  SelkoTests
//

import Foundation
@testable import iOS

final class MockEventService: EventServiceProtocol, @unchecked Sendable {
    var fetchPendingEventsResult: Result<[CalendarEvent], Error> = .success([])
    var fetchPendingEventsWithSourcesResult: Result<[CalendarEvent], Error> = .success([])
    var fetchActivityEventsResult: Result<[CalendarEvent], Error> = .success([])
    var getEventWithSourcesResult: Result<CalendarEvent, Error> = .success(.mock)
    var updateEventResult: Result<CalendarEvent, Error> = .success(.mock)
    var updateEventStatusResult: Result<CalendarEvent, Error> = .success(.mock)
    var approveEventResult: Result<CalendarEvent, Error> = .success(.mock)
    var rejectEventResult: Result<CalendarEvent, Error> = .success(.mock)

    var fetchActivityEventsCallCount = 0
    var getEventWithSourcesCallCount = 0
    var updateEventCallCount = 0
    var updateEventStatusCallCount = 0
    var approveEventCallCount = 0
    var rejectEventCallCount = 0
    var lastApprovedEventId: UUID?
    var lastRejectedEventId: UUID?
    var lastUpdateEventStatusId: UUID?
    var lastUpdateEventStatusStatus: EventStatus?
    var lastFetchActivityEventsOffset: Int?
    var lastFetchActivityEventsLimit: Int?

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
        fetchActivityEventsCallCount += 1
        lastFetchActivityEventsLimit = limit
        lastFetchActivityEventsOffset = offset
        switch fetchActivityEventsResult {
        case .success(let events): return events
        case .failure(let error): throw error
        }
    }

    func fetchEvents(limit: Int, offset: Int, statuses: [EventStatus]?, startAfter: Date?, startBefore: Date?) async throws -> [CalendarEvent] {
        return []
    }

    func getEvent(id: UUID) async throws -> CalendarEvent {
        return .mock
    }

    func getEventWithSources(id: UUID) async throws -> CalendarEvent {
        getEventWithSourcesCallCount += 1
        switch getEventWithSourcesResult {
        case .success(let event): return event
        case .failure(let error): throw error
        }
    }

    func updateEventStatus(id: UUID, status: EventStatus) async throws -> CalendarEvent {
        updateEventStatusCallCount += 1
        lastUpdateEventStatusId = id
        lastUpdateEventStatusStatus = status
        switch updateEventStatusResult {
        case .success(let event): return event
        case .failure(let error): throw error
        }
    }

    func updateEvent(id: UUID, title: String?, startDatetime: Date?, endDatetime: Date?, allDay: Bool?, location: String?, description: String?) async throws -> CalendarEvent {
        updateEventCallCount += 1
        switch updateEventResult {
        case .success(let event): return event
        case .failure(let error): throw error
        }
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
