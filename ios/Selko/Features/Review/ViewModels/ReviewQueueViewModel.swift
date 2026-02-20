//
//  ReviewQueueViewModel.swift
//  Selko
//

import Foundation

/// Groups pending events by the sender email of their first source.
struct SenderGroup: Identifiable {
    let id: String // sender email
    let senderName: String
    let senderEmail: String
    let events: [CalendarEvent]
}

@MainActor
@Observable
final class ReviewQueueViewModel {
    var isLoading = false
    var senderGroups: [SenderGroup] = []
    var errorMessage: String?
    var isConnected = false
    var gmailConnected = false
    var calendarConnected = false

    private let eventService: EventServiceProtocol
    private let integrationService: IntegrationServiceProtocol
    private let senderRuleService: SenderRuleServiceProtocol

    init(
        eventService: EventServiceProtocol? = nil,
        integrationService: IntegrationServiceProtocol? = nil,
        senderRuleService: SenderRuleServiceProtocol? = nil
    ) {
        self.eventService = eventService ?? DependencyContainer.shared.eventService
        self.integrationService = integrationService ?? DependencyContainer.shared.integrationService
        self.senderRuleService = senderRuleService ?? DependencyContainer.shared.senderRuleService
    }

    func load() async {
        isLoading = true
        errorMessage = nil

        do {
            // Check integration status
            let integrations = try await integrationService.fetchIntegrations()
            gmailConnected = integrations.contains { $0.provider == .gmail && $0.isActive }
            calendarConnected = integrations.contains { $0.provider == .googleCalendar && $0.isActive }
            isConnected = gmailConnected && calendarConnected

            if isConnected {
                let events = try await eventService.fetchPendingEventsWithSources()
                senderGroups = groupEventsBySender(events)
            }
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }

    func approveEvent(_ event: CalendarEvent) async {
        do {
            _ = try await eventService.approveEvent(id: event.id)
            removeEventFromGroups(event.id)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func rejectEvent(_ event: CalendarEvent) async {
        do {
            _ = try await eventService.rejectEvent(id: event.id)
            removeEventFromGroups(event.id)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func approveAllInGroup(_ group: SenderGroup) async {
        for event in group.events {
            do {
                _ = try await eventService.approveEvent(id: event.id)
            } catch {
                errorMessage = error.localizedDescription
                return
            }
        }
        // Remove the entire group
        senderGroups.removeAll { $0.id == group.id }
    }

    func rejectAllInGroup(_ group: SenderGroup) async {
        for event in group.events {
            do {
                _ = try await eventService.rejectEvent(id: event.id)
            } catch {
                errorMessage = error.localizedDescription
                return
            }
        }
        // Remove the entire group
        senderGroups.removeAll { $0.id == group.id }
    }

    func ignoreSender(_ group: SenderGroup) async {
        do {
            _ = try await senderRuleService.createRule(
                senderEmail: group.senderEmail,
                senderDomain: nil,
                action: .ignore
            )
            // Reject all events from this sender
            for event in group.events {
                _ = try await eventService.rejectEvent(id: event.id)
            }
            senderGroups.removeAll { $0.id == group.id }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func autoApproveSender(_ group: SenderGroup) async {
        do {
            _ = try await senderRuleService.createRule(
                senderEmail: group.senderEmail,
                senderDomain: nil,
                action: .autoApprove
            )
            // Approve all events from this sender
            for event in group.events {
                _ = try await eventService.approveEvent(id: event.id)
            }
            senderGroups.removeAll { $0.id == group.id }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    // MARK: - Private

    private func groupEventsBySender(_ events: [CalendarEvent]) -> [SenderGroup] {
        var grouped: [String: (name: String, email: String, events: [CalendarEvent])] = [:]

        for event in events {
            let email = event.eventSources?.first?.emails?.fromEmail ?? "unknown"
            let name = event.eventSources?.first?.emails?.fromName ?? email

            if var existing = grouped[email] {
                existing.events.append(event)
                grouped[email] = existing
            } else {
                grouped[email] = (name: name, email: email, events: [event])
            }
        }

        return grouped.map { key, value in
            SenderGroup(
                id: key,
                senderName: value.name,
                senderEmail: value.email,
                events: value.events
            )
        }
    }

    private func removeEventFromGroups(_ eventId: UUID) {
        senderGroups = senderGroups.compactMap { group in
            let filtered = group.events.filter { $0.id != eventId }
            if filtered.isEmpty { return nil }
            return SenderGroup(id: group.id, senderName: group.senderName, senderEmail: group.senderEmail, events: filtered)
        }
    }
}
