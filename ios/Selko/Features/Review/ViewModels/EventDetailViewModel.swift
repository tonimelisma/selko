//
//  EventDetailViewModel.swift
//  Selko
//

import Foundation

@MainActor
@Observable
final class EventDetailViewModel {
    var event: CalendarEvent?
    var isLoading = false
    var isSaving = false
    var isActing = false
    var errorMessage: String?
    var didComplete = false

    // Editable fields
    var title: String = ""
    var allDay: Bool = false
    var startDate: Date = Date()
    var endDate: Date = Date().addingTimeInterval(3600)
    var location: String = ""
    var eventDescription: String = ""

    private let eventId: UUID
    private let eventService: EventServiceProtocol
    private var saveTask: Task<Void, Never>?

    init(
        eventId: UUID,
        eventService: EventServiceProtocol? = nil
    ) {
        self.eventId = eventId
        self.eventService = eventService ?? DependencyContainer.shared.eventService
    }

    func load() async {
        isLoading = true
        errorMessage = nil

        do {
            let loaded = try await eventService.getEventWithSources(id: eventId)
            event = loaded
            populateFields(from: loaded)
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }

    func approve() async {
        guard !isActing else { return }
        isActing = true
        errorMessage = nil
        defer { isActing = false }

        do {
            _ = try await saveChanges()
            _ = try await eventService.approveEvent(id: eventId)
            didComplete = true
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func reject() async {
        guard !isActing else { return }
        isActing = true
        errorMessage = nil
        defer { isActing = false }

        do {
            _ = try await eventService.rejectEvent(id: eventId)
            didComplete = true
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func scheduleSave() {
        saveTask?.cancel()
        saveTask = Task {
            try? await Task.sleep(nanoseconds: 1_000_000_000) // 1 second debounce
            if !Task.isCancelled {
                _ = try? await saveChanges()
            }
        }
    }

    // MARK: - Private

    private func populateFields(from event: CalendarEvent) {
        title = event.title
        allDay = event.allDay
        startDate = event.startDatetime ?? Date()
        endDate = event.endDatetime ?? Date().addingTimeInterval(3600)
        location = event.location ?? ""
        eventDescription = event.description ?? ""
    }

    @discardableResult
    private func saveChanges() async throws -> CalendarEvent {
        isSaving = true
        defer { isSaving = false }

        let updated = try await eventService.updateEvent(
            id: eventId,
            title: title,
            startDatetime: startDate,
            endDatetime: endDate,
            allDay: allDay,
            location: location.isEmpty ? nil : location,
            description: eventDescription.isEmpty ? nil : eventDescription
        )
        event = updated
        return updated
    }
}
