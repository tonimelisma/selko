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
    var hasMore = true

    private var offset = 0
    private let pageSize = 20
    private let eventService: EventServiceProtocol

    init(eventService: EventServiceProtocol? = nil) {
        self.eventService = eventService ?? DependencyContainer.shared.eventService
    }

    func load() async {
        isLoading = true
        errorMessage = nil
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

    func undoEvent(_ event: CalendarEvent) async {
        do {
            _ = try await eventService.updateEventStatus(id: event.id, status: .pendingReview)
            removeEvent(event.id)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func retrySync(_ event: CalendarEvent) async {
        do {
            _ = try await eventService.updateEventStatus(id: event.id, status: .approved)
            // Update the event in the list to reflect the new status
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
