//
//  SettingsViewModel.swift
//  Selko
//

import Foundation

@MainActor
@Observable
final class SettingsViewModel {
    var isLoading = false
    var integrations: [Integration] = []
    var calendars: [CalendarInfo] = []
    var calendarSettings: UserCalendarSettings?
    var selectedCalendarId: String = ""
    var errorMessage: String?
    var showDisconnectAlert = false
    var providerToDisconnect: IntegrationProvider?

    private let integrationService: IntegrationServiceProtocol
    private let backendAPI: BackendAPIProtocol
    private let calendarSettingsService: CalendarSettingsServiceProtocol
    private let authService: AuthServiceProtocol

    init(
        integrationService: IntegrationServiceProtocol? = nil,
        backendAPI: BackendAPIProtocol? = nil,
        calendarSettingsService: CalendarSettingsServiceProtocol? = nil,
        authService: AuthServiceProtocol? = nil
    ) {
        self.integrationService = integrationService ?? DependencyContainer.shared.integrationService
        self.backendAPI = backendAPI ?? DependencyContainer.shared.backendAPI
        self.calendarSettingsService = calendarSettingsService ?? DependencyContainer.shared.calendarSettingsService
        self.authService = authService ?? DependencyContainer.shared.authService
    }

    func load() async {
        isLoading = true
        errorMessage = nil

        do {
            integrations = try await integrationService.fetchIntegrations()

            // Load calendar settings
            calendarSettings = try await calendarSettingsService.getSettings()
            selectedCalendarId = calendarSettings?.defaultCalendarId ?? ""

            // Try to load calendars if Google Calendar is connected
            let calendarConnected = integrations.contains { $0.provider == .googleCalendar && $0.isActive }
            if calendarConnected {
                do {
                    calendars = try await backendAPI.listCalendars()
                    if selectedCalendarId.isEmpty, let primary = calendars.first(where: { $0.isPrimary }) {
                        selectedCalendarId = primary.id
                    }
                } catch {
                    // Calendar list may fail if backend is unreachable; not critical
                    calendars = []
                }
            }
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }

    func confirmDisconnect(provider: IntegrationProvider) {
        providerToDisconnect = provider
        showDisconnectAlert = true
    }

    func disconnect() async {
        guard let provider = providerToDisconnect else { return }

        do {
            try await integrationService.deleteIntegration(provider: provider)
            integrations.removeAll { $0.provider == provider }
        } catch {
            errorMessage = error.localizedDescription
        }

        providerToDisconnect = nil
    }

    func updateDefaultCalendar() async {
        guard !selectedCalendarId.isEmpty,
              let calendar = calendars.first(where: { $0.id == selectedCalendarId }) else {
            return
        }

        do {
            calendarSettings = try await calendarSettingsService.updateDefaultCalendar(
                calendarId: calendar.id,
                calendarName: calendar.name
            )
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func signOut() async {
        do {
            try await authService.signOut()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    // MARK: - Helpers

    func integration(for provider: IntegrationProvider) -> Integration? {
        integrations.first { $0.provider == provider }
    }

    func providerDisplayName(_ provider: IntegrationProvider) -> String {
        switch provider {
        case .gmail: return "Gmail"
        case .googleCalendar: return "Google Calendar"
        case .googlePhotos: return "Google Photos"
        }
    }
}
