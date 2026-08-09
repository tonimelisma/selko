//
//  HistoryViewModel.swift
//  Selko
//

import Foundation

/// Groups history events by date (Today, Yesterday, or formatted date).
struct DateGroup: Identifiable {
    let id: String // date label
    let label: String
    let events: [CalendarEvent]
}

@MainActor
@Observable
final class HistoryViewModel {
    var isLoading = false
    var dateGroups: [DateGroup] = []
    var errorMessage: String?
    var canForceUndo = false
    var hasMore = true
    var processingEventIds: Set<UUID> = []

    private var pendingForceUndoEvent: CalendarEvent?
    private var offset = 0
    private let pageSize = 20
    private let eventService: EventServiceProtocol
    private let backendAPI: BackendAPIProtocol

    private let liveUpdateService: LiveUpdateService?
    private var liveUpdateTask: Task<Void, Never>?

    init(eventService: EventServiceProtocol? = nil, backendAPI: BackendAPIProtocol? = nil, liveUpdateService: LiveUpdateService? = nil) {
        self.eventService = eventService ?? DependencyContainer.shared.eventService
        self.backendAPI = backendAPI ?? DependencyContainer.shared.backendAPI
        self.liveUpdateService = liveUpdateService
    }

    func startLiveUpdates() {
        guard let liveUpdateService else { return }
        liveUpdateTask?.cancel()
        liveUpdateTask = Task { [weak self] in
            guard let self else { return }
            for await inv in liveUpdateService.stream {
                if inv.resource == "events" || inv.resource == "event_sources" || inv.resource == "emails" {
                    if self.processingEventIds.isEmpty {
                        await self.refreshForLiveUpdate()
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
        if let liveUpdateService { await liveUpdateService.refreshAll() }
        await refreshForLiveUpdate()
    }

    private func refreshForLiveUpdate() async {
        // Spec §3: refetch first max(20, events.length) so pagination does not collapse; dedupe; preserve errors/optimistic state
        let currentCount = dateGroups.flatMap(\.events).count
        let limit = max(pageSize, currentCount)
        do {
            let events = try await eventService.fetchActivityEvents(limit: limit, offset: 0)
            // Deduplicate by ID (fetchActivityEvents already deduped, but keep spec contract)
            var seen = Set<UUID>()
            var deduped: [CalendarEvent] = []
            for e in events where seen.insert(e.id).inserted { deduped.append(e) }
            dateGroups = groupEventsByDate(deduped)
            offset = deduped.count
            hasMore = events.count == limit
        } catch {
            // Preserve existing data; surface error contextually without wiping dateGroups
            if errorMessage == nil { errorMessage = error.localizedDescription }
        }
    }

    func load() async {
        isLoading = true
        errorMessage = nil
        canForceUndo = false
        pendingForceUndoEvent = nil
        offset = 0
        hasMore = true

        do {
            let events = try await eventService.fetchActivityEvents(limit: pageSize, offset: 0)
            dateGroups = groupEventsByDate(events)
            offset = events.count
            hasMore = events.count == pageSize
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }

    func loadMore() async {
        guard hasMore, !isLoading else { return }

        do {
            let events = try await eventService.fetchActivityEvents(limit: pageSize, offset: offset)
            if events.isEmpty {
                hasMore = false
                return
            }
            let allEvents = dateGroups.flatMap(\.events) + events
            dateGroups = groupEventsByDate(allEvents)
            offset += events.count
            hasMore = events.count == pageSize
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func undoEvent(_ event: CalendarEvent, force: Bool = false) async {
        guard !processingEventIds.contains(event.id) else { return }
        processingEventIds.insert(event.id)
        errorMessage = nil
        if !force {
            canForceUndo = false
            pendingForceUndoEvent = nil
        }
        defer { processingEventIds.remove(event.id) }

        do {
            _ = try await backendAPI.undoHistoryEvent(eventId: event.id, force: force)
            removeEvent(event.id)
            canForceUndo = false
            pendingForceUndoEvent = nil
        } catch let error as BackendAPIError {
            if case .calendarDiverged(let message) = error {
                errorMessage = message
                canForceUndo = true
                pendingForceUndoEvent = event
            } else {
                errorMessage = error.localizedDescription
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func forceUndoPendingEvent() async {
        guard let event = pendingForceUndoEvent else { return }
        await undoEvent(event, force: true)
    }

    func clearError() {
        errorMessage = nil
        canForceUndo = false
        pendingForceUndoEvent = nil
    }

    func retrySync(_ event: CalendarEvent) async {
        guard !processingEventIds.contains(event.id) else { return }
        processingEventIds.insert(event.id)
        errorMessage = nil
        defer { processingEventIds.remove(event.id) }

        do {
            _ = try await eventService.updateEventStatus(id: event.id, status: .approved)
            await load()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    // MARK: - Private

    private func removeEvent(_ eventId: UUID) {
        dateGroups = dateGroups.compactMap { group in
            let filtered = group.events.filter { $0.id != eventId }
            if filtered.isEmpty { return nil }
            return DateGroup(id: group.id, label: group.label, events: filtered)
        }
    }

    private func groupEventsByDate(_ events: [CalendarEvent]) -> [DateGroup] {
        let calendar = Calendar.current
        var grouped: [(label: String, key: String, events: [CalendarEvent])] = []
        var seen: [String: Int] = [:]

        for event in events {
            let date = event.updatedAt ?? event.createdAt ?? Date()
            let label = dateLabel(for: date, calendar: calendar)
            let key = label

            if let index = seen[key] {
                grouped[index].events.append(event)
            } else {
                seen[key] = grouped.count
                grouped.append((label: label, key: key, events: [event]))
            }
        }

        return grouped.map { DateGroup(id: $0.key, label: $0.label, events: $0.events) }
    }

    private func dateLabel(for date: Date, calendar: Calendar) -> String {
        if calendar.isDateInToday(date) {
            return String(localized: "Today")
        } else if calendar.isDateInYesterday(date) {
            return String(localized: "Yesterday")
        } else {
            let formatter = DateFormatter()
            formatter.dateStyle = .medium
            formatter.timeStyle = .none
            return formatter.string(from: date)
        }
    }
}
