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
    var integrations: [Integration] = []
    var processingEventIds: Set<UUID> = []

    // MARK: - Reject Undo state
    var lastRejectedEvents: [CalendarEvent] = []
    var showUndoToast: Bool = false
    var undoToastMessage: String = ""
    private var undoTask: Task<Void, Never>?

    var isFirstRun: Bool { integrations.isEmpty }
    var emailConnected: Bool {
        integrations.contains {
            ($0.provider == .gmail || $0.provider == .outlook) && $0.isActive
        }
    }
    var gmailConnected: Bool {
        integrations.contains { $0.provider == .gmail && $0.isActive }
    }
    var calendarConnected: Bool {
        integrations.contains { $0.provider == .googleCalendar && $0.isActive }
    }
    var isConnected: Bool { emailConnected && calendarConnected }
    var hasConnectionIssue: Bool {
        !emailConnected || !calendarConnected || integrations.contains {
            !$0.isActive && $0.provider != .googlePhotos
        }
    }

    private let eventService: EventServiceProtocol
    private let integrationService: IntegrationServiceProtocol
    private let senderRuleService: SenderRuleServiceProtocol
    private let backendAPI: BackendAPIProtocol

    init(
        eventService: EventServiceProtocol? = nil,
        integrationService: IntegrationServiceProtocol? = nil,
        senderRuleService: SenderRuleServiceProtocol? = nil,
        backendAPI: BackendAPIProtocol? = nil,
        liveUpdateService: LiveUpdateService? = nil
    ) {
        self.eventService = eventService ?? DependencyContainer.shared.eventService
        self.integrationService = integrationService ?? DependencyContainer.shared.integrationService
        self.senderRuleService = senderRuleService ?? DependencyContainer.shared.senderRuleService
        self.backendAPI = backendAPI ?? DependencyContainer.shared.backendAPI
        // In tests liveUpdateService stays nil to avoid real Supabase; Views inject the shared service
        self.liveUpdateService = liveUpdateService
    }

    private let liveUpdateService: LiveUpdateService?
    private var liveUpdateTask: Task<Void, Never>?

    func startLiveUpdates() {
        guard let liveUpdateService else { return }
        liveUpdateTask?.cancel()
        liveUpdateTask = Task { [weak self] in
            guard let self else { return }
            for await inv in liveUpdateService.stream {
                if ["events", "event_sources", "event_change_proposals", "calendar_work_items", "integrations"].contains(inv.resource) {
                    if self.processingEventIds.isEmpty {
                        await self.load()
                    }
                }
            }
        }
    }

    func stopLiveUpdates() {
        liveUpdateTask?.cancel()
        liveUpdateTask = nil
    }

    func handleScenePhaseActive() async {
        // Ensure subscription and do catch-up fetch per spec
        if let liveUpdateService { await liveUpdateService.catchUp() }
        await load()
    }

    func load() async {
        isLoading = true
        errorMessage = nil

        do {
            // Check integration status
            integrations = try await integrationService.fetchIntegrations()

            if !integrations.isEmpty {
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
        guard ensureCalendarConnected() else { return }
        guard !processingEventIds.contains(event.id) else { return }
        processingEventIds.insert(event.id)
        errorMessage = nil
        defer { processingEventIds.remove(event.id) }

        do {
            if event.isPendingChange {
                _ = try await backendAPI.applyEventChange(eventId: event.id)
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
            showRejectUndo(events: [event])
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func approveAllInGroup(_ group: SenderGroup) async {
        guard ensureCalendarConnected() else { return }
        let eventIds = Set(group.events.map(\.id))
        processingEventIds.formUnion(eventIds)
        errorMessage = nil
        defer { processingEventIds.subtract(eventIds) }

        for event in group.events {
            do {
                if event.isPendingChange {
                    _ = try await backendAPI.applyEventChange(eventId: event.id)
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

        var succeeded: [CalendarEvent] = []
        var anyFailed = false
        var lastError: String?
        for event in group.events {
            do {
                if event.isPendingChange {
                    _ = try await backendAPI.rejectEventChange(eventId: event.id)
                } else {
                    _ = try await eventService.rejectEvent(id: event.id)
                }
                succeeded.append(event)
            } catch {
                anyFailed = true
                lastError = error.localizedDescription
            }
        }

        if succeeded.count == group.events.count && !anyFailed {
            removeGroup(group.id)
            if !succeeded.isEmpty {
                showRejectUndo(events: succeeded)
            }
        } else if !succeeded.isEmpty && anyFailed {
            // Partial success: remove succeeded, show undo for them, sync failed from server
            for ev in succeeded {
                removeEventFromGroups(ev.id)
            }
            showRejectUndo(events: succeeded)
            errorMessage = lastError
            await load()
        } else if succeeded.isEmpty && anyFailed {
            errorMessage = lastError
            await load()
        }
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
        guard ensureCalendarConnected() else { return }
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
                } else {
                    _ = try await eventService.approveEvent(id: event.id)
                }
            }
            removeGroup(group.id)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    // MARK: - Reject Undo

    func showRejectUndo(events: [CalendarEvent]) {
        guard !events.isEmpty else { return }
        undoTask?.cancel()
        if showUndoToast {
            lastRejectedEvents.append(contentsOf: events)
        } else {
            lastRejectedEvents = events
        }
        undoToastMessage = lastRejectedEvents.count == 1 ? "Event rejected" : "\(lastRejectedEvents.count) events rejected"
        showUndoToast = true
        undoTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 8_000_000_000)
            guard !Task.isCancelled else { return }
            await MainActor.run {
                self?.showUndoToast = false
                self?.lastRejectedEvents = []
                self?.undoTask = nil
            }
        }
    }

    func dismissUndoToast() {
        undoTask?.cancel()
        undoTask = nil
        showUndoToast = false
        lastRejectedEvents = []
    }

    func undoLastRejected() async {
        undoTask?.cancel()
        undoTask = nil
        let toRestore = lastRejectedEvents
        guard !toRestore.isEmpty else {
            showUndoToast = false
            return
        }
        showUndoToast = false
        lastRejectedEvents = []

        // Optimistically reinsert events
        let existing = senderGroups.flatMap(\.events)
        var combined = existing + toRestore
        // Deduplicate by ID
        var deduped: [UUID: CalendarEvent] = [:]
        for e in combined { deduped[e.id] = e }
        let dedupedEvents = Array(deduped.values)
        senderGroups = groupEventsBySender(dedupedEvents)
        newSenderGroups = groupEventsBySender(dedupedEvents.filter { !$0.isPendingChange })
        changeSenderGroups = groupEventsBySender(dedupedEvents.filter { $0.isPendingChange })

        var hadError = false
        var lastError: String?
        for event in toRestore {
            do {
                _ = try await backendAPI.undoHistoryEvent(eventId: event.id, force: false)
            } catch {
                hadError = true
                lastError = error.localizedDescription
                // Remove optimistically restored event on failure
                removeEventFromGroups(event.id)
            }
        }
        if hadError, let lastError {
            errorMessage = lastError
        }
        // Reload for consistency; preserve errorMessage if we had one
        let preservedError = errorMessage
        await load()
        if hadError, let preservedError {
            errorMessage = preservedError
        }
    }

    // MARK: - Private

    @discardableResult
    private func ensureCalendarConnected() -> Bool {
        guard calendarConnected else {
            errorMessage = String(localized: "Reconnect Google Calendar to accept suggestions.")
            return false
        }
        return true
    }

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
