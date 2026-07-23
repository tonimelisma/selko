//
//  SettingsViewModel.swift
//  Selko
//

import Foundation

@MainActor
@Observable
final class SettingsViewModel {
    struct FolderUpdateError: Equatable {
        let message: String
        let requestedIncluded: Bool
    }

    var isLoading = false
    var integrations: [Integration] = []
    var calendars: [CalendarInfo] = []
    var calendarSettings: UserCalendarSettings?
    var selectedCalendarId: String = ""
    var allDayDisplayMode: AllDayDisplayMode = .allDay
    var allDayCustomStart: Date = Calendar.current.date(
        bySettingHour: 9, minute: 0, second: 0, of: Date()
    ) ?? Date()
    var allDayCustomEnd: Date = Calendar.current.date(
        bySettingHour: 17, minute: 0, second: 0, of: Date()
    ) ?? Date()
    var allDayCustomError: String?
    var isSavingAllDayPreference = false
    var errorMessage: String?
    var showDisconnectAlert = false
    var providerToDisconnect: IntegrationProvider?
    var emailFolders: [IntegrationProvider: [EmailFolderPreference]] = [:]
    var folderLoadErrors: [IntegrationProvider: String] = [:]
    var updatingFolderIds: Set<String> = []
    var folderErrors: [String: FolderUpdateError] = [:]

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
            await loadEmailFolders()

            // Load calendar settings
            calendarSettings = try await calendarSettingsService.getSettings()
            selectedCalendarId = calendarSettings?.targetCalendarId ?? ""
            allDayDisplayMode = calendarSettings?.allDayDisplayMode ?? .allDay
            if let start = Self.parseTime(calendarSettings?.allDayCustomStart) {
                allDayCustomStart = start
            }
            if let end = Self.parseTime(calendarSettings?.allDayCustomEnd) {
                allDayCustomEnd = end
            }

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

    private func loadEmailFolders() async {
        for provider in [IntegrationProvider.gmail, .outlook] {
            guard integrations.contains(where: { $0.provider == provider && $0.isActive }) else {
                emailFolders[provider] = []
                folderLoadErrors.removeValue(forKey: provider)
                continue
            }
            await reloadEmailFolders(provider: provider)
        }
    }

    func reloadEmailFolders(provider: IntegrationProvider) async {
        folderLoadErrors.removeValue(forKey: provider)
        do {
            emailFolders[provider] = try await backendAPI.listEmailFolders(provider: provider.rawValue)
                .filter { !$0.isSystem }
        } catch {
            emailFolders[provider] = []
            folderLoadErrors[provider] = error.localizedDescription
        }
    }

    func folders(for provider: IntegrationProvider) -> [EmailFolderPreference] {
        emailFolders[provider] ?? []
    }

    func updateFolder(provider: IntegrationProvider, folderId: String, isIncluded: Bool) async {
        guard !updatingFolderIds.contains(folderId),
              let previous = folders(for: provider).first(where: { $0.id == folderId }) else { return }

        updatingFolderIds.insert(folderId)
        folderErrors.removeValue(forKey: folderId)
        replaceFolder(provider: provider, folder: previous.withIncluded(isIncluded))

        do {
            let updated = try await backendAPI.updateEmailFolder(
                provider: provider.rawValue,
                folderId: folderId,
                isIncluded: isIncluded
            )
            replaceFolder(provider: provider, folder: updated)
        } catch {
            replaceFolder(provider: provider, folder: previous)
            folderErrors[folderId] = FolderUpdateError(
                message: error.localizedDescription,
                requestedIncluded: isIncluded
            )
        }
        updatingFolderIds.remove(folderId)
    }

    func retryFolderUpdate(provider: IntegrationProvider, folderId: String) async {
        guard let failure = folderErrors[folderId] else { return }
        await updateFolder(provider: provider, folderId: folderId, isIncluded: failure.requestedIncluded)
    }

    private func replaceFolder(provider: IntegrationProvider, folder: EmailFolderPreference) {
        emailFolders[provider] = folders(for: provider).map { $0.id == folder.id ? folder : $0 }
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

    func updateAllDayDisplayMode(_ mode: AllDayDisplayMode) async {
        allDayDisplayMode = mode
        allDayCustomError = nil
        if mode == .custom, !customTimesAreValid {
            allDayCustomError = String(localized: "settings.date_only_custom_error")
            return
        }
        await saveAllDayPreference()
    }

    func updateAllDayCustomTimes() async {
        allDayCustomError = nil
        guard allDayDisplayMode == .custom else { return }
        guard customTimesAreValid else {
            allDayCustomError = String(localized: "settings.date_only_custom_error")
            return
        }
        await saveAllDayPreference()
    }

    var customTimesAreValid: Bool {
        Self.timeString(from: allDayCustomEnd) > Self.timeString(from: allDayCustomStart)
    }

    var allDayPreviewWindow: String {
        switch allDayDisplayMode {
        case .allDay: return AllDayDisplayMode.allDay.displayName
        case .day9to5: return AllDayDisplayMode.day9to5.displayName
        case .morning8to9: return AllDayDisplayMode.morning8to9.displayName
        case .custom:
            return "\(Self.timeString(from: allDayCustomStart))–\(Self.timeString(from: allDayCustomEnd))"
        }
    }

    private func saveAllDayPreference() async {
        isSavingAllDayPreference = true
        defer { isSavingAllDayPreference = false }
        do {
            let start = allDayDisplayMode == .custom ? Self.timeString(from: allDayCustomStart) : nil
            let end = allDayDisplayMode == .custom ? Self.timeString(from: allDayCustomEnd) : nil
            calendarSettings = try await calendarSettingsService.updateAllDayDisplayPreference(
                mode: allDayDisplayMode,
                customStart: start,
                customEnd: end
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
        case .gmail: return String(localized: "Gmail")
        case .outlook: return String(localized: "Outlook")
        case .googleCalendar: return String(localized: "Google Calendar")
        case .googlePhotos: return String(localized: "Google Photos")
        }
    }

    private static func timeString(from date: Date) -> String {
        let comps = Calendar.current.dateComponents([.hour, .minute], from: date)
        return String(format: "%02d:%02d", comps.hour ?? 0, comps.minute ?? 0)
    }

    private static func parseTime(_ value: String?) -> Date? {
        guard let value, !value.isEmpty else { return nil }
        let parts = value.split(separator: ":")
        guard parts.count >= 2,
              let hour = Int(parts[0]),
              let minute = Int(parts[1]) else { return nil }
        return Calendar.current.date(bySettingHour: hour, minute: minute, second: 0, of: Date())
    }
}
