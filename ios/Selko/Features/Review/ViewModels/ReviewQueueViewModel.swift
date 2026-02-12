//
//  ReviewQueueViewModel.swift
//  Selko
//

import Foundation

/// Groups events by the source email they were extracted from.
struct EmailGroup: Identifiable {
    let id: String  // email UUID string
    let subject: String
    let dateSent: Date?
    let events: [CalendarEvent]
}

/// Groups pending events by the sender email of their first source.
struct SenderGroup: Identifiable {
    let id: String // sender email
    let senderName: String
    let senderEmail: String
    let emailGroups: [EmailGroup]
    var allEvents: [CalendarEvent] { emailGroups.flatMap { $0.events } }
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

    init(
        eventService: EventServiceProtocol? = nil,
        integrationService: IntegrationServiceProtocol? = nil
    ) {
        self.eventService = eventService ?? DependencyContainer.shared.eventService
        self.integrationService = integrationService ?? DependencyContainer.shared.integrationService
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
            await removeEventFromGroups(event.id)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func rejectEvent(_ event: CalendarEvent) async {
        do {
            _ = try await eventService.rejectEvent(id: event.id)
            await removeEventFromGroups(event.id)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func approveAllInGroup(_ group: SenderGroup) async {
        for event in group.allEvents {
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

    func approveAllInEmailGroup(_ emailGroup: EmailGroup) async {
        for event in emailGroup.events {
            do {
                _ = try await eventService.approveEvent(id: event.id)
            } catch {
                errorMessage = error.localizedDescription
                return
            }
        }
        // Remove events and clean up empty groups
        let eventIds = Set(emailGroup.events.map { $0.id })
        senderGroups = senderGroups.compactMap { group in
            let filteredEmailGroups = group.emailGroups.compactMap { eg -> EmailGroup? in
                let filtered = eg.events.filter { !eventIds.contains($0.id) }
                if filtered.isEmpty { return nil }
                return EmailGroup(id: eg.id, subject: eg.subject, dateSent: eg.dateSent, events: filtered)
            }
            if filteredEmailGroups.isEmpty { return nil }
            return SenderGroup(id: group.id, senderName: group.senderName, senderEmail: group.senderEmail, emailGroups: filteredEmailGroups)
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
            // Sub-group by email ID
            var emailGrouped: [String: (subject: String, dateSent: Date?, events: [CalendarEvent])] = [:]
            for event in value.events {
                let emailId = event.eventSources?.first?.emailId.uuidString ?? "unknown"
                let subject = event.eventSources?.first?.emails?.subject ?? "No subject"
                let dateSent = event.eventSources?.first?.emails?.dateSent

                if var existing = emailGrouped[emailId] {
                    existing.events.append(event)
                    emailGrouped[emailId] = existing
                } else {
                    emailGrouped[emailId] = (subject: subject, dateSent: dateSent, events: [event])
                }
            }

            let emailGroups = emailGrouped.map { emailKey, emailValue in
                EmailGroup(
                    id: emailKey,
                    subject: emailValue.subject,
                    dateSent: emailValue.dateSent,
                    events: emailValue.events
                )
            }

            return SenderGroup(
                id: key,
                senderName: value.name,
                senderEmail: value.email,
                emailGroups: emailGroups
            )
        }
    }

    private func removeEventFromGroups(_ eventId: UUID) async {
        senderGroups = senderGroups.compactMap { group in
            let filteredEmailGroups = group.emailGroups.compactMap { emailGroup -> EmailGroup? in
                let filtered = emailGroup.events.filter { $0.id != eventId }
                if filtered.isEmpty { return nil }
                return EmailGroup(id: emailGroup.id, subject: emailGroup.subject, dateSent: emailGroup.dateSent, events: filtered)
            }
            if filteredEmailGroups.isEmpty { return nil }
            return SenderGroup(id: group.id, senderName: group.senderName, senderEmail: group.senderEmail, emailGroups: filteredEmailGroups)
        }
    }
}
