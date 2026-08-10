//
//  EventDetailViewModelTests.swift
//  SelkoTests
//

import Foundation
import Testing
@testable import iOS

@MainActor
struct EventDetailViewModelTests {
    @Test
    func loadEventSuccessPopulatesFields() async throws {
        // Given
        let mockEventService = MockEventService()
        let eventId = UUID()
        let expectedEvent = CalendarEvent(
            id: eventId,
            userId: UUID(),
            title: "Team Standup",
            startDatetime: Date().addingTimeInterval(86400),
            endDatetime: Date().addingTimeInterval(90000),
            allDay: false,
            location: "Room 42",
            description: "Daily sync meeting",
            sourceAttribution: "From manager@company.com",
            status: .pendingReview,
            googleCalendarEventId: nil,
            syncedAt: nil,
            createdAt: Date(),
            updatedAt: Date(),
            eventSources: nil
        )
        mockEventService.getEventWithSourcesResult = .success(expectedEvent)

        let viewModel = EventDetailViewModel(eventId: eventId, eventService: mockEventService)

        // When
        await viewModel.load()

        // Then
        #expect(viewModel.title == "Team Standup")
        #expect(viewModel.location == "Room 42")
        #expect(viewModel.eventDescription == "Daily sync meeting")
        #expect(viewModel.allDay == false)
        #expect(viewModel.event != nil)
        #expect(viewModel.isLoading == false)
        #expect(viewModel.errorMessage == nil)
        #expect(mockEventService.getEventWithSourcesCallCount == 1)
    }

    @Test
    func loadEventFailureSetsError() async throws {
        // Given
        let mockEventService = MockEventService()
        let eventId = UUID()
        mockEventService.getEventWithSourcesResult = .failure(NSError(domain: "test", code: 1, userInfo: [NSLocalizedDescriptionKey: "Network error"]))

        let viewModel = EventDetailViewModel(eventId: eventId, eventService: mockEventService)

        // When
        await viewModel.load()

        // Then
        #expect(viewModel.errorMessage != nil)
        #expect(viewModel.event == nil)
        #expect(viewModel.isLoading == false)
    }

    @Test
    func approveSuccessSetsDidComplete() async throws {
        // Given
        let mockEventService = MockEventService()
        let eventId = UUID()
        mockEventService.updateEventResult = .success(.mock)
        mockEventService.approveEventResult = .success(.mock)

        let viewModel = EventDetailViewModel(eventId: eventId, eventService: mockEventService)

        // When
        await viewModel.approve()

        // Then
        #expect(viewModel.didComplete == true)
        #expect(viewModel.errorMessage == nil)
        #expect(mockEventService.approveEventCallCount == 1)
        #expect(mockEventService.updateEventCallCount == 1)
    }

    @Test
    func approveFailureSetsError() async throws {
        // Given
        let mockEventService = MockEventService()
        let eventId = UUID()
        mockEventService.approveEventResult = .failure(NSError(domain: "test", code: 1, userInfo: [NSLocalizedDescriptionKey: "Sync failed"]))

        let viewModel = EventDetailViewModel(eventId: eventId, eventService: mockEventService)

        // When
        await viewModel.approve()

        // Then
        #expect(viewModel.errorMessage != nil)
        #expect(viewModel.didComplete == false)
    }

    @Test
    func expiredCalendarBlocksApprovalButKeepsEventLoaded() async {
        let eventService = MockEventService()
        eventService.getEventWithSourcesResult = .success(.mock)
        let integrationService = MockIntegrationService()
        integrationService.fetchIntegrationsResult = .success([
            Integration(
                id: UUID(),
                userId: UUID(),
                provider: .googleCalendar,
                status: .expired,
                providerEmail: nil,
                scopes: [],
                lastSyncAt: nil,
                createdAt: nil,
                updatedAt: nil
            )
        ])
        let viewModel = EventDetailViewModel(
            eventId: CalendarEvent.mock.id,
            eventService: eventService,
            integrationService: integrationService
        )

        await viewModel.load()
        await viewModel.approve()

        #expect(viewModel.event != nil)
        #expect(!viewModel.calendarConnected)
        #expect(eventService.approveEventCallCount == 0)
        #expect(viewModel.errorMessage == "Reconnect Google Calendar to accept suggestions.")
    }

    @Test
    func rejectSuccessShowsUndoToastAndDelaysDidComplete() async throws {
        // Given
        let mockEventService = MockEventService()
        let eventId = UUID()
        let mockEvent = CalendarEvent(
            id: eventId,
            userId: UUID(),
            title: "Team Standup",
            startDatetime: Date().addingTimeInterval(86400),
            endDatetime: Date().addingTimeInterval(90000),
            allDay: false,
            location: nil,
            description: nil,
            sourceAttribution: nil,
            status: .pendingReview,
            googleCalendarEventId: nil,
            syncedAt: nil,
            createdAt: Date(),
            updatedAt: Date(),
            eventSources: nil
        )
        mockEventService.rejectEventResult = .success(mockEvent)
        mockEventService.getEventWithSourcesResult = .success(mockEvent)

        let viewModel = EventDetailViewModel(eventId: eventId, eventService: mockEventService)
        await viewModel.load()

        // When
        await viewModel.reject()

        // Then - reject is now undoable via toast, navigation is delayed 8s
        #expect(viewModel.showUndoToast == true)
        #expect(viewModel.undoToastMessage == "Event rejected")
        #expect(viewModel.lastRejectedEvents.count == 1)
        #expect(viewModel.didComplete == false)
        #expect(viewModel.errorMessage == nil)
        #expect(mockEventService.rejectEventCallCount == 1)

        // Dismiss should complete navigation
        viewModel.dismissUndoToast()
        #expect(viewModel.didComplete == true)
        #expect(viewModel.showUndoToast == false)
    }

    @Test
    func rejectUndoRestoresAndDoesNotComplete() async throws {
        let mockEventService = MockEventService()
        let mockBackendAPI = MockBackendAPI()
        let eventId = UUID()
        let mockEvent = CalendarEvent(
            id: eventId,
            userId: UUID(),
            title: "Team Standup",
            startDatetime: Date().addingTimeInterval(86400),
            endDatetime: Date().addingTimeInterval(90000),
            allDay: false,
            location: nil,
            description: nil,
            sourceAttribution: nil,
            status: .pendingReview,
            googleCalendarEventId: nil,
            syncedAt: nil,
            createdAt: Date(),
            updatedAt: Date(),
            eventSources: nil
        )
        mockEventService.rejectEventResult = .success(mockEvent)
        mockEventService.getEventWithSourcesResult = .success(mockEvent)
        mockBackendAPI.undoHistoryEventResult = .success(EventChangeResponse(eventId: eventId.uuidString, status: "pending_review"))
        let viewModel = EventDetailViewModel(eventId: eventId, eventService: mockEventService, backendAPI: mockBackendAPI)
        await viewModel.load()

        await viewModel.reject()
        #expect(viewModel.showUndoToast == true)

        await viewModel.undoLastRejected()

        #expect(mockBackendAPI.undoHistoryEventCallCount == 1)
        #expect(viewModel.showUndoToast == false)
        #expect(viewModel.didComplete == false)
        #expect(viewModel.errorMessage == nil)
    }

    @Test
    func rejectFailureSetsError() async throws {
        // Given
        let mockEventService = MockEventService()
        let eventId = UUID()
        let mockEvent = CalendarEvent(
            id: eventId,
            userId: UUID(),
            title: "Team Standup",
            startDatetime: Date().addingTimeInterval(86400),
            endDatetime: Date().addingTimeInterval(90000),
            allDay: false,
            location: nil,
            description: nil,
            sourceAttribution: nil,
            status: .pendingReview,
            googleCalendarEventId: nil,
            syncedAt: nil,
            createdAt: Date(),
            updatedAt: Date(),
            eventSources: nil
        )
        mockEventService.rejectEventResult = .failure(NSError(domain: "test", code: 1, userInfo: [NSLocalizedDescriptionKey: "Reject failed"]))
        mockEventService.getEventWithSourcesResult = .success(mockEvent)

        let viewModel = EventDetailViewModel(eventId: eventId, eventService: mockEventService)
        await viewModel.load()

        // When
        await viewModel.reject()

        // Then
        #expect(viewModel.errorMessage != nil)
        #expect(viewModel.didComplete == false)
        #expect(mockEventService.rejectEventCallCount == 1)
    }
}
