//
//  ReviewQueueViewModelTests.swift
//  SelkoTests
//

import Foundation
import Testing
@testable import iOS

@MainActor
struct ReviewQueueViewModelTests {
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
    func resolveSenderPrefersEmailOverGoogleCalendar() {
        let calendarSource = EventSource(
            id: UUID(),
            eventId: UUID(),
            emailId: nil,
            sourceOrigin: .googleCalendar,
            sourceType: .update,
            extractedData: nil,
            changeSet: nil,
            isUndone: false,
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
            status: .pendingChange,
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
}
