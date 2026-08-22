//
//  ReviewQueueViewModelTests.swift
//  SelkoTests
//

import Foundation
import Testing
@testable import iOS

@MainActor
struct ReviewQueueViewModelTests {
    private func integration(
        _ provider: IntegrationProvider,
        status: IntegrationStatus = .active
    ) -> Integration {
        Integration(
            id: UUID(),
            userId: UUID(),
            provider: provider,
            status: status,
            providerEmail: nil,
            scopes: [],
            lastSyncAt: nil,
            createdAt: nil,
            updatedAt: nil
        )
    }

    private func makeEvent(title: String = "Test Event") -> CalendarEvent {
        CalendarEvent(
            id: UUID(),
            userId: UUID(),
            title: title,
            startDatetime: Date().addingTimeInterval(86400),
            endDatetime: Date().addingTimeInterval(90000),
            allDay: false,
            location: "Conference Room",
            description: "A test event",
            sourceAttribution: "From test@example.com",
            googleCalendarEventId: nil,
            syncedAt: nil,
            createdAt: Date(),
            updatedAt: Date(),
            eventSources: nil
        )
    }

    // MARK: - Ignore Sender

    @Test
    func ignoreSenderCreatesRuleAndRejectsEvents() async throws {
        // Given
        let mockEventService = MockEventService()
        let mockIntegrationService = MockIntegrationService()
        let mockSenderRuleService = MockSenderRuleService()

        let event1 = CalendarEvent.mock
        let event2 = CalendarEvent.mock

        let viewModel = ReviewQueueViewModel(
            eventService: mockEventService,
            integrationService: mockIntegrationService,
            senderRuleService: mockSenderRuleService
        )
        viewModel.integrations = [integration(.googleCalendar)]

        let group = SenderGroup(
            id: "sender@example.com",
            senderName: "Sender",
            senderEmail: "sender@example.com",
            events: [event1, event2]
        )
        viewModel.senderGroups = [group]

        // When
        await viewModel.ignoreSender(group)

        // Then
        #expect(mockSenderRuleService.createRuleCallCount == 1)
        #expect(mockSenderRuleService.lastCreateEmail == "sender@example.com")
        #expect(mockSenderRuleService.lastCreateDomain == nil)
        #expect(mockSenderRuleService.lastCreateAction == .ignore)
        #expect(mockEventService.rejectEventCallCount == 2)
        #expect(viewModel.senderGroups.isEmpty)
        #expect(viewModel.errorMessage == nil)
    }

    @Test
    func ignoreSenderShowsErrorOnFailure() async throws {
        // Given
        let mockEventService = MockEventService()
        let mockIntegrationService = MockIntegrationService()
        let mockSenderRuleService = MockSenderRuleService()
        mockSenderRuleService.createRuleResult = .failure(NSError(domain: "test", code: 1, userInfo: [NSLocalizedDescriptionKey: "Network error"]))

        let viewModel = ReviewQueueViewModel(
            eventService: mockEventService,
            integrationService: mockIntegrationService,
            senderRuleService: mockSenderRuleService
        )
        viewModel.integrations = [integration(.googleCalendar)]

        let group = SenderGroup(
            id: "sender@example.com",
            senderName: "Sender",
            senderEmail: "sender@example.com",
            events: [CalendarEvent.mock]
        )
        viewModel.senderGroups = [group]

        // When
        await viewModel.ignoreSender(group)

        // Then
        #expect(viewModel.errorMessage != nil)
        #expect(mockEventService.rejectEventCallCount == 0)
    }

    // MARK: - Auto-Approve Sender

    @Test
    func autoApproveSenderCreatesRuleAndApprovesEvents() async throws {
        // Given
        let mockEventService = MockEventService()
        let mockIntegrationService = MockIntegrationService()
        let mockSenderRuleService = MockSenderRuleService()

        let event1 = CalendarEvent.mock
        let event2 = CalendarEvent.mock

        let viewModel = ReviewQueueViewModel(
            eventService: mockEventService,
            integrationService: mockIntegrationService,
            senderRuleService: mockSenderRuleService
        )
        viewModel.integrations = [integration(.googleCalendar)]

        let group = SenderGroup(
            id: "sender@example.com",
            senderName: "Sender",
            senderEmail: "sender@example.com",
            events: [event1, event2]
        )
        viewModel.senderGroups = [group]

        // When
        await viewModel.autoApproveSender(group)

        // Then
        #expect(mockSenderRuleService.createRuleCallCount == 1)
        #expect(mockSenderRuleService.lastCreateEmail == "sender@example.com")
        #expect(mockSenderRuleService.lastCreateDomain == nil)
        #expect(mockSenderRuleService.lastCreateAction == .autoApprove)
        #expect(mockEventService.approveEventCallCount == 2)
        #expect(viewModel.senderGroups.isEmpty)
        #expect(viewModel.errorMessage == nil)
    }

    @Test
    func autoApproveSenderShowsErrorOnFailure() async throws {
        // Given
        let mockEventService = MockEventService()
        let mockIntegrationService = MockIntegrationService()
        let mockSenderRuleService = MockSenderRuleService()
        mockSenderRuleService.createRuleResult = .failure(NSError(domain: "test", code: 1, userInfo: [NSLocalizedDescriptionKey: "Network error"]))

        let viewModel = ReviewQueueViewModel(
            eventService: mockEventService,
            integrationService: mockIntegrationService,
            senderRuleService: mockSenderRuleService
        )
        viewModel.integrations = [integration(.googleCalendar)]

        let group = SenderGroup(
            id: "sender@example.com",
            senderName: "Sender",
            senderEmail: "sender@example.com",
            events: [CalendarEvent.mock]
        )
        viewModel.senderGroups = [group]

        // When
        await viewModel.autoApproveSender(group)

        // Then
        #expect(viewModel.errorMessage != nil)
        #expect(mockEventService.approveEventCallCount == 0)
    }

    // MARK: - Sender resolution

    @Test
    func loadTreatsOutlookAsConnectedEmailAndKeepsSuggestionsVisible() async {
        let eventService = MockEventService()
        eventService.fetchPendingEventsWithSourcesResult = .success([.mock])
        let integrationService = MockIntegrationService()
        integrationService.fetchIntegrationsResult = .success([
            integration(.gmail, status: .expired),
            integration(.outlook),
            integration(.googleCalendar)
        ])
        let viewModel = ReviewQueueViewModel(
            eventService: eventService,
            integrationService: integrationService
        )

        await viewModel.load()

        #expect(viewModel.emailConnected)
        #expect(viewModel.isConnected)
        #expect(!viewModel.senderGroups.isEmpty)
    }

    @Test
    func expiredCalendarKeepsSuggestionsVisibleAndBlocksApproval() async {
        let eventService = MockEventService()
        eventService.fetchPendingEventsWithSourcesResult = .success([.mock])
        let integrationService = MockIntegrationService()
        integrationService.fetchIntegrationsResult = .success([
            integration(.outlook),
            integration(.googleCalendar, status: .expired)
        ])
        let viewModel = ReviewQueueViewModel(
            eventService: eventService,
            integrationService: integrationService
        )

        await viewModel.load()
        await viewModel.approveEvent(.mock)

        #expect(!viewModel.senderGroups.isEmpty)
        #expect(eventService.approveEventCallCount == 0)
        #expect(viewModel.errorMessage == "Reconnect Google Calendar to accept suggestions.")
    }

    @Test
    func resolveSenderPrefersEmailOverGoogleCalendar() {
        let calendarSource = EventSource(
            id: UUID(),
            eventId: UUID(),
            emailId: nil,
            sourceOrigin: .googleCalendar,
            sourceType: .update,
            extractedData: nil,
            createdAt: Date(),
            emails: nil
        )
        let emailSource = EventSource.mock
        let event = CalendarEvent(
            id: UUID(),
            userId: UUID(),
            title: "Bike Family Fest",
            startDatetime: Date(),
            endDatetime: Date(),
            allDay: false,
            location: nil,
            description: nil,
            sourceAttribution: nil,
            googleCalendarEventId: "gcal-1",
            syncedAt: nil,
            createdAt: Date(),
            updatedAt: Date(),
            eventSources: [calendarSource, emailSource]
        )

        let resolved = ReviewQueueViewModel.resolveSender(for: event)
        #expect(resolved.email == "sender@example.com")
        #expect(resolved.name == Email.mock.fromName || resolved.name == "sender@example.com")
    }

    // MARK: - Reject Undo

    @Test
    func rejectEventShowsUndoToast() async {
        let event = makeEvent(title: "Dentist")
        let mockEventService = MockEventService()
        let mockBackendAPI = MockBackendAPI()
        let mockIntegrationService = MockIntegrationService()
        mockEventService.rejectEventResult = .success(event)
        let viewModel = ReviewQueueViewModel(
            eventService: mockEventService,
            integrationService: mockIntegrationService,
            backendAPI: mockBackendAPI
        )
        viewModel.integrations = [integration(.googleCalendar)]
        let source = EventSource(
            id: UUID(), eventId: event.id, emailId: UUID(), sourceOrigin: .email, sourceType: .newInvitation,
            extractedData: nil, createdAt: Date(),
            emails: Email(id: UUID(), userId: nil, integrationId: nil, emailProvider: "gmail", providerMessageId: "m", threadId: "t", subject: "Hi", fromEmail: "a@b.com", fromName: "A", toEmails: nil, dateSent: Date(), snippet: nil, providerLabels: nil, isSpam: false, isTrash: false, isPromotions: false, isSocial: false, isUpdates: false, isForums: false, isPrimary: true, isImportant: false, isStarred: false, isUnread: true, hasAttachments: false, createdAt: Date())
        )
        var eventWithSource = event
        eventWithSource = CalendarEvent(id: event.id, userId: event.userId, title: event.title, startDatetime: event.startDatetime, endDatetime: event.endDatetime, allDay: event.allDay, location: event.location, description: event.description, sourceAttribution: event.sourceAttribution, googleCalendarEventId: event.googleCalendarEventId, syncedAt: event.syncedAt, createdAt: event.createdAt, updatedAt: event.updatedAt, eventSources: [source])
        viewModel.senderGroups = [SenderGroup(id: "a@b.com", senderName: "A", senderEmail: "a@b.com", events: [eventWithSource])]
        viewModel.newSenderGroups = viewModel.senderGroups
        viewModel.changeSenderGroups = []

        await viewModel.rejectEvent(eventWithSource)

        #expect(viewModel.showUndoToast == true)
        #expect(viewModel.undoToastMessage == "Event rejected")
        #expect(viewModel.lastRejectedEvents.count == 1)
        #expect(viewModel.senderGroups.isEmpty)
        #expect(mockEventService.rejectEventCallCount == 1)
    }

    @Test
    func undoLastRejectedRestoresGroupAndCallsBackend() async {
        let event = makeEvent(title: "Lunch")
        let mockEventService = MockEventService()
        let mockBackendAPI = MockBackendAPI()
        let mockIntegrationService = MockIntegrationService()
        // Mock load to return event again after undo
        let restoredEvent = event
        mockEventService.fetchPendingEventsWithSourcesResult = .success([restoredEvent])
        mockIntegrationService.fetchIntegrationsResult = .success([integration(.googleCalendar)])
        mockBackendAPI.undoHistoryEventResult = .success(EventChangeResponse(eventId: event.id.uuidString, status: "pending_review"))

        let viewModel = ReviewQueueViewModel(
            eventService: mockEventService,
            integrationService: mockIntegrationService,
            backendAPI: mockBackendAPI
        )
        viewModel.integrations = [integration(.googleCalendar)]
        viewModel.senderGroups = []

        // Simulate rejected state
        viewModel.showRejectUndo(events: [event])
        #expect(viewModel.showUndoToast == true)
        #expect(viewModel.lastRejectedEvents.count == 1)

        await viewModel.undoLastRejected()

        #expect(mockBackendAPI.undoHistoryEventCallCount == 1)
        #expect(mockBackendAPI.lastUndoHistoryEventId == event.id)
        #expect(viewModel.showUndoToast == false)
        #expect(viewModel.lastRejectedEvents.isEmpty)
        // After undo + load, group should be restored via load's fetched events
        #expect(!viewModel.senderGroups.isEmpty)
    }

    @Test
    func consecutiveRejectsBatchIntoSingleToast() async {
        let event1 = makeEvent(title: "Event 1")
        let event2 = makeEvent(title: "Event 2")
        let mockEventService = MockEventService()
        let mockBackendAPI = MockBackendAPI()
        let viewModel = ReviewQueueViewModel(
            eventService: mockEventService,
            backendAPI: mockBackendAPI
        )
        viewModel.showRejectUndo(events: [event1])
        #expect(viewModel.undoToastMessage == "Event rejected")
        #expect(viewModel.lastRejectedEvents.count == 1)

        viewModel.showRejectUndo(events: [event2])
        #expect(viewModel.undoToastMessage == "2 events rejected")
        #expect(viewModel.lastRejectedEvents.count == 2)
        #expect(viewModel.showUndoToast == true)
    }

    @Test
    func rejectAllInGroupShowsUndoToast() async {
        let event1 = makeEvent(title: "Bulk 1")
        let event2 = makeEvent(title: "Bulk 2")
        let mockEventService = MockEventService()
        let mockBackendAPI = MockBackendAPI()
        let mockIntegrationService = MockIntegrationService()
        let viewModel = ReviewQueueViewModel(
            eventService: mockEventService,
            integrationService: mockIntegrationService,
            backendAPI: mockBackendAPI
        )
        viewModel.integrations = [integration(.googleCalendar)]
        let group = SenderGroup(id: "bulk@example.com", senderName: "Bulk", senderEmail: "bulk@example.com", events: [event1, event2])
        viewModel.senderGroups = [group]
        viewModel.newSenderGroups = [group]

        await viewModel.rejectAllInGroup(group)

        #expect(viewModel.showUndoToast == true)
        #expect(viewModel.undoToastMessage == "2 events rejected")
        #expect(viewModel.lastRejectedEvents.count == 2)
        #expect(viewModel.senderGroups.isEmpty)
        #expect(mockEventService.rejectEventCallCount == 2)
    }

    @Test
    func dismissUndoToastClearsState() async {
        let event = makeEvent()
        let viewModel = ReviewQueueViewModel()
        viewModel.showRejectUndo(events: [event])
        #expect(viewModel.showUndoToast == true)
        viewModel.dismissUndoToast()
        #expect(viewModel.showUndoToast == false)
        #expect(viewModel.lastRejectedEvents.isEmpty)
        #expect(viewModel.undoToastMessage != "" || viewModel.lastRejectedEvents.isEmpty)
    }
}
