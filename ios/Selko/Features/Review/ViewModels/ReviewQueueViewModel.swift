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
    var newSenderGroups: [SenderGroup] = []
    var changeSenderGroups: [SenderGroup] = []
    var errorMessage: String?
    var isConnected = false
    var gmailConnected = false
    var calendarConnected = false
    var processingEventIds: Set<UUID> = []

    private let eventService: EventServiceProtocol
    private let integrationService: IntegrationServiceProtocol
    private let senderRuleService: SenderRuleServiceProtocol
    private let backendAPI: BackendAPIProtocol

    init(
        eventService: EventServiceProtocol? = nil,
        integrationService: IntegrationServiceProtocol? = nil,
        senderRuleService: SenderRuleServiceProtocol? = nil,
        backendAPI: BackendAPIProtocol? = nil
    ) {
        self.eventService = eventService ?? DependencyContainer.shared.eventService
        self.integrationService = integrationService ?? DependencyContainer.shared.integrationService
        self.senderRuleService = senderRuleService ?? DependencyContainer.shared.senderRuleService
        self.backendAPI = backendAPI ?? DependencyContainer.shared.backendAPI
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
                newSenderGroups = groupEventsBySender(events.filter { !$0.isPendingChange })
                changeSenderGroups = groupEventsBySender(events.filter { $0.isPendingChange })
            }
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }

    func approveEvent(_ event: CalendarEvent) async {
        guard !processingEventIds.contains(event.id) else { return }
        processingEventIds.insert(event.id)
        errorMessage = nil
        defer { processingEventIds.remove(event.id) }

        do {
            if event.isPendingChange {
                _ = try await backendAPI.applyEventChange(eventId: event.id)
                _ = try? await backendAPI.syncEventToCalendar(eventId: event.id)
            } else {
                _ = try await eventService.approveEvent(id: event.id)
            }
            removeEventFromGroups(event.id)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func rejectEvent(_ event: CalendarEvent) async {
        guard !processingEventIds.contains(event.id) else { return }
        processingEventIds.insert(event.id)
        errorMessage = nil
        defer { processingEventIds.remove(event.id) }

        do {
            if event.isPendingChange {
                _ = try await backendAPI.rejectEventChange(eventId: event.id)
            } else {
                _ = try await eventService.rejectEvent(id: event.id)
            }
            removeEventFromGroups(event.id)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func approveAllInGroup(_ group: SenderGroup) async {
        let eventIds = Set(group.events.map(\.id))
        processingEventIds.formUnion(eventIds)
        errorMessage = nil
        defer { processingEventIds.subtract(eventIds) }

        for event in group.events {
            do {
                if event.isPendingChange {
                    _ = try await backendAPI.applyEventChange(eventId: event.id)
                    _ = try? await backendAPI.syncEventToCalendar(eventId: event.id)
                } else {
                    _ = try await eventService.approveEvent(id: event.id)
                }
            } catch {
                errorMessage = error.localizedDescription
                return
            }
        }
        removeGroup(group.id)
    }

    func rejectAllInGroup(_ group: SenderGroup) async {
        let eventIds = Set(group.events.map(\.id))
        processingEventIds.formUnion(eventIds)
        errorMessage = nil
        defer { processingEventIds.subtract(eventIds) }

        for event in group.events {
            do {
                if event.isPendingChange {
                    _ = try await backendAPI.rejectEventChange(eventId: event.id)
                } else {
                    _ = try await eventService.rejectEvent(id: event.id)
                }
            } catch {
                errorMessage = error.localizedDescription
                return
            }
        }
        removeGroup(group.id)
    }

    func ignoreSender(_ group: SenderGroup) async {
        let eventIds = Set(group.events.map(\.id))
        processingEventIds.formUnion(eventIds)
        errorMessage = nil
        defer { processingEventIds.subtract(eventIds) }

        do {
            _ = try await senderRuleService.createRule(
                senderEmail: group.senderEmail,
                senderDomain: nil,
                action: .ignore
            )
            for event in group.events {
                if event.isPendingChange {
                    _ = try await backendAPI.rejectEventChange(eventId: event.id)
                } else {
                    _ = try await eventService.rejectEvent(id: event.id)
                }
            }
            removeGroup(group.id)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func autoApproveSender(_ group: SenderGroup) async {
        let eventIds = Set(group.events.map(\.id))
        processingEventIds.formUnion(eventIds)
        errorMessage = nil
        defer { processingEventIds.subtract(eventIds) }

        do {
            _ = try await senderRuleService.createRule(
                senderEmail: group.senderEmail,
                senderDomain: nil,
                action: .autoApprove
            )
            for event in group.events {
                if event.isPendingChange {
                    _ = try await backendAPI.applyEventChange(eventId: event.id)
                    _ = try? await backendAPI.syncEventToCalendar(eventId: event.id)
                } else {
                    _ = try await eventService.approveEvent(id: event.id)
                }
            }
            removeGroup(group.id)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    // MARK: - Private

    private func groupEventsBySender(_ events: [CalendarEvent]) -> [SenderGroup] {
        var grouped: [String: (name: String, email: String, events: [CalendarEvent])] = [:]

        for event in events {
            let resolved = Self.resolveSender(for: event)
            let key = resolved.email

            if var existing = grouped[key] {
                existing.events.append(event)
                grouped[key] = existing
            } else {
                grouped[key] = (name: resolved.name, email: resolved.email, events: [event])
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

    /// Prefer email authorship over calendar/photo provenance rows.
    static func resolveSender(for event: CalendarEvent) -> (name: String, email: String) {
        let sources = (event.eventSources ?? []).filter { !$0.isUndone }

        if let emailSource = sources.first(where: {
            $0.sourceOrigin == .email
                && ($0.emails?.fromEmail != nil || $0.emails?.fromName != nil)
        }), let email = emailSource.emails {
            let address = email.fromEmail ?? "unknown"
            let name = email.fromName ?? address
            return (name: name, email: address)
        }

        if sources.contains(where: { $0.sourceOrigin == .googlePhotos }) {
            return (name: String(localized: "Google Photos"), email: "google_photos")
        }

        if sources.contains(where: { $0.sourceOrigin == .googleCalendar }) {
            return (name: String(localized: "Google Calendar"), email: "google_calendar")
        }

        return (name: String(localized: "Unknown Sender"), email: "unknown")
    }

    private func removeGroup(_ groupId: String) {
        senderGroups.removeAll { $0.id == groupId }
        newSenderGroups.removeAll { $0.id == groupId }
        changeSenderGroups.removeAll { $0.id == groupId }
    }

    private func removeEventFromGroups(_ eventId: UUID) {
        senderGroups = senderGroups.compactMap { group in
            let filtered = group.events.filter { $0.id != eventId }
            if filtered.isEmpty { return nil }
            return SenderGroup(id: group.id, senderName: group.senderName, senderEmail: group.senderEmail, events: filtered)
        }
        newSenderGroups = newSenderGroups.compactMap { group in
            let filtered = group.events.filter { $0.id != eventId }
            if filtered.isEmpty { return nil }
            return SenderGroup(id: group.id, senderName: group.senderName, senderEmail: group.senderEmail, events: filtered)
        }
        changeSenderGroups = changeSenderGroups.compactMap { group in
            let filtered = group.events.filter { $0.id != eventId }
            if filtered.isEmpty { return nil }
            return SenderGroup(id: group.id, senderName: group.senderName, senderEmail: group.senderEmail, events: filtered)
        }
    }
}
