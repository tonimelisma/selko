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
    var integrations: [Integration] = []
    var calendarConnected = true

    // Editable fields
    var title: String = ""
    var allDay: Bool = false
    var startDate: Date = Date()
    var endDate: Date = Date().addingTimeInterval(3600)
    var location: String = ""
    var eventDescription: String = ""

    private let eventId: UUID
    private let eventService: EventServiceProtocol
    private let integrationService: IntegrationServiceProtocol?
    private var saveTask: Task<Void, Never>?

    init(
        eventId: UUID,
        eventService: EventServiceProtocol? = nil,
        integrationService: IntegrationServiceProtocol? = nil
    ) {
        self.eventId = eventId
        self.eventService = eventService ?? DependencyContainer.shared.eventService
        self.integrationService = integrationService
    }

    func load() async {
        isLoading = true
        errorMessage = nil

        if let integrationService {
            do {
                integrations = try await integrationService.fetchIntegrations()
                calendarConnected = integrations.contains {
                    $0.provider == .googleCalendar && $0.isActive
                }
            } catch {
                calendarConnected = false
                errorMessage = error.localizedDescription
            }
        }

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
        guard calendarConnected else {
            errorMessage = String(localized: "Reconnect Google Calendar to accept suggestions.")
            return
        }
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
