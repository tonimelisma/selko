//
//  HistoryViewModelTests.swift
//  SelkoTests
//

import Foundation
import Testing
@testable import iOS

@MainActor
struct HistoryViewModelTests {
    @Test
    func loadFetchesEventsAndGroups() async throws {
        // Given
        let mockEventService = MockEventService()
        let event1 = CalendarEvent(
            id: UUID(),
            userId: UUID(),
            title: "Event 1",
            startDatetime: Date(),
            endDatetime: Date().addingTimeInterval(3600),
            allDay: false,
            location: nil,
            description: nil,
            sourceAttribution: nil,
            googleCalendarEventId: nil,
            syncedAt: nil,
            createdAt: Date(),
            updatedAt: Date(),
            eventSources: nil
        )
        let event2 = CalendarEvent(
            id: UUID(),
            userId: UUID(),
            title: "Event 2",
            startDatetime: Date(),
            endDatetime: Date().addingTimeInterval(3600),
            allDay: false,
            location: nil,
            description: nil,
            sourceAttribution: nil,
            googleCalendarEventId: nil,
            syncedAt: nil,
            createdAt: Date(),
            updatedAt: Date(),
            eventSources: nil
        )
        mockEventService.fetchActivityEventsResult = .success([event1, event2])

        let viewModel = HistoryViewModel(eventService: mockEventService)

        // When
        await viewModel.load()

        // Then
        #expect(!viewModel.dateGroups.isEmpty)
        let totalEvents = viewModel.dateGroups.flatMap(\.events).count
        #expect(totalEvents == 2)
        #expect(viewModel.isLoading == false)
        #expect(viewModel.errorMessage == nil)
        #expect(mockEventService.fetchActivityEventsCallCount == 1)
    }

    @Test
    func loadFailureSetsError() async throws {
        // Given
        let mockEventService = MockEventService()
        mockEventService.fetchActivityEventsResult = .failure(NSError(domain: "test", code: 1, userInfo: [NSLocalizedDescriptionKey: "Fetch failed"]))

        let viewModel = HistoryViewModel(eventService: mockEventService)

        // When
        await viewModel.load()

        // Then
        #expect(viewModel.errorMessage != nil)
        #expect(viewModel.dateGroups.isEmpty)
        #expect(viewModel.isLoading == false)
    }

    @Test
    func loadIncludesCancellationQueuedEvents() async throws {
        let mockEventService = MockEventService()
        // `status` is derived, not stored: a queued cancellation is an
        // un-superseded work item with action == .cancel that has not yet
        // succeeded. This test used to pass `status: .cancelQueued` to the
        // initializer, which silently discarded it (the parameter existed but
        // was never assigned), so the event derived .approved and the test had
        // been failing since clients moved to authoritative event state.
        let eventId = UUID()
        let userId = UUID()
        let cancelItem = CalendarWorkItem(
            id: UUID(),
            eventId: eventId,
            userId: userId,
            action: .cancel,
            generation: 1,
            status: .pending,
            providerEventId: nil,
            expectedProviderRevision: nil,
            forceOverwrite: false,
            attempts: 0,
            maxAttempts: 5,
            nextRetryAt: nil,
            failureCode: nil,
            failureDetail: nil,
            createdAt: Date(),
            updatedAt: Date(),
            completedAt: nil
        )
        let event = CalendarEvent(
            id: eventId,
            userId: userId,
            title: "Cancelled meeting",
            startDatetime: Date(),
            endDatetime: Date().addingTimeInterval(3600),
            allDay: false,
            location: nil,
            description: nil,
            sourceAttribution: nil,
            googleCalendarEventId: UUID().uuidString,
            syncedAt: Date(),
            createdAt: Date(),
            updatedAt: Date(),
            eventSources: nil,
            calendarWorkItems: [cancelItem]
        )
        mockEventService.fetchActivityEventsResult = .success([event])

        let viewModel = HistoryViewModel(eventService: mockEventService)
        await viewModel.load()

        #expect(viewModel.dateGroups.flatMap(\.events).first?.status == .cancelQueued)
    }

    @Test
    func loadMoreAppendsPagination() async throws {
        // Given
        let mockEventService = MockEventService()

        // Initial page: 20 events (full page, so hasMore = true)
        var initialEvents: [CalendarEvent] = []
        for i in 0..<20 {
            initialEvents.append(CalendarEvent(
                id: UUID(),
                userId: UUID(),
                title: "Event \(i)",
                startDatetime: Date(),
                endDatetime: Date().addingTimeInterval(3600),
                allDay: false,
                location: nil,
                description: nil,
                sourceAttribution: nil,
                googleCalendarEventId: nil,
                syncedAt: nil,
                createdAt: Date(),
                updatedAt: Date(),
                eventSources: nil
            ))
        }
        mockEventService.fetchActivityEventsResult = .success(initialEvents)

        let viewModel = HistoryViewModel(eventService: mockEventService)
        await viewModel.load()

        #expect(viewModel.hasMore == true)
        let initialCount = viewModel.dateGroups.flatMap(\.events).count
        #expect(initialCount == 20)

        // Second page: 5 more events
        var moreEvents: [CalendarEvent] = []
        for i in 20..<25 {
            moreEvents.append(CalendarEvent(
                id: UUID(),
                userId: UUID(),
                title: "Event \(i)",
                startDatetime: Date(),
                endDatetime: Date().addingTimeInterval(3600),
                allDay: false,
                location: nil,
                description: nil,
                sourceAttribution: nil,
                googleCalendarEventId: nil,
                syncedAt: nil,
                createdAt: Date(),
                updatedAt: Date(),
                eventSources: nil
            ))
        }
        mockEventService.fetchActivityEventsResult = .success(moreEvents)

        // When
        await viewModel.loadMore()

        // Then
        let totalEvents = viewModel.dateGroups.flatMap(\.events).count
        #expect(totalEvents == 25)
        #expect(mockEventService.fetchActivityEventsCallCount == 2)
        #expect(mockEventService.lastFetchActivityEventsOffset == 20)
    }

    @Test
    func loadMoreSetsHasMoreFalse() async throws {
        // Given
        let mockEventService = MockEventService()

        // Return fewer events than pageSize (less than 20)
        let fewEvents = [CalendarEvent.mock, CalendarEvent.mock]
        mockEventService.fetchActivityEventsResult = .success(fewEvents)

        let viewModel = HistoryViewModel(eventService: mockEventService)
        await viewModel.load()

        // Then - fewer than pageSize means no more
        #expect(viewModel.hasMore == false)
    }

    @Test
    func undoEventChangesStatusAndRemoves() async throws {
        // Given
        let mockEventService = MockEventService()
        let mockBackendAPI = MockBackendAPI()
        let eventId = UUID()
        let event = CalendarEvent(
            id: eventId,
            userId: UUID(),
            title: "Event to Undo",
            startDatetime: Date(),
            endDatetime: Date().addingTimeInterval(3600),
            allDay: false,
            location: nil,
            description: nil,
            sourceAttribution: nil,
            googleCalendarEventId: nil,
            syncedAt: nil,
            createdAt: Date(),
            updatedAt: Date(),
            eventSources: nil
        )
        mockEventService.fetchActivityEventsResult = .success([event])
        mockBackendAPI.undoHistoryEventResult = .success(
            EventChangeResponse(eventId: eventId.uuidString, status: "pending_review")
        )

        let viewModel = HistoryViewModel(eventService: mockEventService, backendAPI: mockBackendAPI)
        await viewModel.load()

        let initialCount = viewModel.dateGroups.flatMap(\.events).count
        #expect(initialCount == 1)

        // When
        await viewModel.undoEvent(event)

        // Then
        #expect(mockBackendAPI.undoHistoryEventCallCount == 1)
        #expect(mockBackendAPI.lastUndoHistoryEventId == eventId)
        let finalCount = viewModel.dateGroups.flatMap(\.events).count
        #expect(finalCount == 0)
        #expect(viewModel.errorMessage == nil)
        #expect(viewModel.processingEventIds.isEmpty)
    }

    @Test
    func undoEventFailureSetsErrorAndKeepsEvent() async throws {
        let mockEventService = MockEventService()
        let mockBackendAPI = MockBackendAPI()
        let eventId = UUID()
        let event = CalendarEvent(
            id: eventId,
            userId: UUID(),
            title: "Event to Undo",
            startDatetime: Date(),
            endDatetime: Date().addingTimeInterval(3600),
            allDay: false,
            location: nil,
            description: nil,
            sourceAttribution: nil,
            googleCalendarEventId: nil,
            syncedAt: nil,
            createdAt: Date(),
            updatedAt: Date(),
            eventSources: nil
        )
        mockEventService.fetchActivityEventsResult = .success([event])
        mockBackendAPI.undoHistoryEventResult = .failure(
            NSError(domain: "test", code: 502, userInfo: [NSLocalizedDescriptionKey: "Request timed out"])
        )

        let viewModel = HistoryViewModel(eventService: mockEventService, backendAPI: mockBackendAPI)
        await viewModel.load()

        await viewModel.undoEvent(event)

        #expect(viewModel.errorMessage == "Request timed out")
        #expect(viewModel.dateGroups.flatMap(\.events).count == 1)
        #expect(viewModel.processingEventIds.isEmpty)
    }

    @Test
    func undoEventCalendarDivergedOffersForceUndo() async throws {
        let mockEventService = MockEventService()
        let mockBackendAPI = MockBackendAPI()
        let eventId = UUID()
        let event = CalendarEvent(
            id: eventId,
            userId: UUID(),
            title: "Diverged Event",
            startDatetime: Date(),
            endDatetime: Date().addingTimeInterval(3600),
            allDay: false,
            location: nil,
            description: nil,
            sourceAttribution: nil,
            googleCalendarEventId: "gcal-1",
            syncedAt: Date(),
            createdAt: Date(),
            updatedAt: Date(),
            eventSources: nil
        )
        mockEventService.fetchActivityEventsResult = .success([event])
        mockBackendAPI.undoHistoryEventResult = .failure(
            BackendAPIError.calendarDiverged("Edited in Google Calendar after Selko synced it (title).")
        )

        let viewModel = HistoryViewModel(eventService: mockEventService, backendAPI: mockBackendAPI)
        await viewModel.load()
        await viewModel.undoEvent(event)

        #expect(mockBackendAPI.lastUndoHistoryForce == false)
        #expect(viewModel.canForceUndo == true)
        #expect(viewModel.dateGroups.flatMap(\.events).count == 1)
        #expect(viewModel.errorMessage?.contains("Google Calendar") == true)

        mockBackendAPI.undoHistoryEventResult = .success(
            EventChangeResponse(eventId: eventId.uuidString, status: "pending_review")
        )
        await viewModel.forceUndoPendingEvent()

        #expect(mockBackendAPI.lastUndoHistoryForce == true)
        #expect(mockBackendAPI.undoHistoryEventCallCount == 2)
        #expect(viewModel.canForceUndo == false)
        #expect(viewModel.dateGroups.flatMap(\.events).count == 0)
        #expect(viewModel.errorMessage == nil)
    }

    @Test
    func retryEventChangesStatusAndReloads() async throws {
        // Given
        let mockEventService = MockEventService()
        let eventId = UUID()
        let event = CalendarEvent(
            id: eventId,
            userId: UUID(),
            title: "Event to Retry",
            startDatetime: Date(),
            endDatetime: Date().addingTimeInterval(3600),
            allDay: false,
            location: nil,
            description: nil,
            sourceAttribution: nil,
            googleCalendarEventId: nil,
            syncedAt: nil,
            createdAt: Date(),
            updatedAt: Date(),
            eventSources: nil
        )
        mockEventService.fetchActivityEventsResult = .success([event])
        mockEventService.updateEventStatusResult = .success(.mock)

        let viewModel = HistoryViewModel(eventService: mockEventService)
        await viewModel.load()

        // When
        await viewModel.retrySync(event)

        // Then
        #expect(mockEventService.updateEventStatusCallCount == 1)
        #expect(mockEventService.lastUpdateEventStatusId == eventId)
        #expect(mockEventService.lastUpdateEventStatusStatus == .approved)
        #expect(viewModel.errorMessage == nil)
        // retrySync calls load() again, so fetchActivityEvents is called 3 times total
        // (1 initial load + 1 from retrySync's internal load)
        #expect(mockEventService.fetchActivityEventsCallCount >= 2)
    }
}
