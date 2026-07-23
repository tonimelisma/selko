//
//  SettingsViewModelTests.swift
//  SelkoTests
//

import Foundation
import Testing
@testable import iOS

@MainActor
struct SettingsViewModelTests {
    private func folder(id: String = "folder-1", included: Bool) -> EmailFolderPreference {
        EmailFolderPreference(
            id: id, provider: "gmail", name: "Promotions", fullPath: "Promotions",
            classificationDecision: "exclude", classificationReason: "Marketing mail",
            userOverride: false, isIncluded: included, isSystem: false
        )
    }

    private func integration(_ provider: IntegrationProvider) -> Integration {
        Integration(
            id: UUID(), userId: UUID(), provider: provider, status: .active,
            providerEmail: "user@example.com", scopes: [], lastSyncAt: nil,
            createdAt: Date(), updatedAt: Date()
        )
    }

    @Test
    func loadFetchesIntegrations() async throws {
        // Given
        let mockIntegrationService = MockIntegrationService()
        let mockBackendAPI = MockBackendAPI()
        let mockCalendarSettingsService = MockCalendarSettingsService()
        let mockAuthService = MockAuthService()

        let gmailIntegration = Integration(
            id: UUID(),
            userId: UUID(),
            provider: .gmail,
            status: .active,
            providerEmail: "user@gmail.com",
            scopes: ["https://www.googleapis.com/auth/gmail.readonly"],
            lastSyncAt: Date(),
            createdAt: Date(),
            updatedAt: Date()
        )
        mockIntegrationService.fetchIntegrationsResult = .success([gmailIntegration])

        let viewModel = SettingsViewModel(
            integrationService: mockIntegrationService,
            backendAPI: mockBackendAPI,
            calendarSettingsService: mockCalendarSettingsService,
            authService: mockAuthService
        )

        // When
        await viewModel.load()

        // Then
        #expect(viewModel.integrations.count == 1)
        #expect(viewModel.integrations.first?.provider == .gmail)
        #expect(viewModel.isLoading == false)
        #expect(viewModel.errorMessage == nil)
        #expect(mockIntegrationService.fetchIntegrationsCallCount == 1)
    }

    @Test
    func loadFailureSetsError() async throws {
        // Given
        let mockIntegrationService = MockIntegrationService()
        let mockBackendAPI = MockBackendAPI()
        let mockCalendarSettingsService = MockCalendarSettingsService()
        let mockAuthService = MockAuthService()

        mockIntegrationService.fetchIntegrationsResult = .failure(NSError(domain: "test", code: 1, userInfo: [NSLocalizedDescriptionKey: "Network error"]))

        let viewModel = SettingsViewModel(
            integrationService: mockIntegrationService,
            backendAPI: mockBackendAPI,
            calendarSettingsService: mockCalendarSettingsService,
            authService: mockAuthService
        )

        // When
        await viewModel.load()

        // Then
        #expect(viewModel.errorMessage != nil)
        #expect(viewModel.integrations.isEmpty)
        #expect(viewModel.isLoading == false)
    }

    @Test
    func disconnectRemovesIntegration() async throws {
        // Given
        let mockIntegrationService = MockIntegrationService()
        let mockBackendAPI = MockBackendAPI()
        let mockCalendarSettingsService = MockCalendarSettingsService()
        let mockAuthService = MockAuthService()

        let gmailIntegration = Integration(
            id: UUID(),
            userId: UUID(),
            provider: .gmail,
            status: .active,
            providerEmail: "user@gmail.com",
            scopes: [],
            lastSyncAt: nil,
            createdAt: Date(),
            updatedAt: Date()
        )
        mockIntegrationService.fetchIntegrationsResult = .success([gmailIntegration])

        let viewModel = SettingsViewModel(
            integrationService: mockIntegrationService,
            backendAPI: mockBackendAPI,
            calendarSettingsService: mockCalendarSettingsService,
            authService: mockAuthService
        )

        await viewModel.load()
        #expect(viewModel.integrations.count == 1)

        // Set up the provider to disconnect
        viewModel.providerToDisconnect = .gmail

        // When
        await viewModel.disconnect()

        // Then
        #expect(viewModel.integrations.isEmpty)
        #expect(mockIntegrationService.deleteIntegrationCallCount == 1)
        #expect(mockIntegrationService.lastDeletedProvider == .gmail)
        #expect(viewModel.errorMessage == nil)
    }

    @Test
    func disconnectFailureSetsError() async throws {
        // Given
        let mockIntegrationService = MockIntegrationService()
        let mockBackendAPI = MockBackendAPI()
        let mockCalendarSettingsService = MockCalendarSettingsService()
        let mockAuthService = MockAuthService()

        let gmailIntegration = Integration(
            id: UUID(),
            userId: UUID(),
            provider: .gmail,
            status: .active,
            providerEmail: "user@gmail.com",
            scopes: [],
            lastSyncAt: nil,
            createdAt: Date(),
            updatedAt: Date()
        )
        mockIntegrationService.fetchIntegrationsResult = .success([gmailIntegration])
        mockIntegrationService.deleteIntegrationError = NSError(domain: "test", code: 1, userInfo: [NSLocalizedDescriptionKey: "Delete failed"])

        let viewModel = SettingsViewModel(
            integrationService: mockIntegrationService,
            backendAPI: mockBackendAPI,
            calendarSettingsService: mockCalendarSettingsService,
            authService: mockAuthService
        )

        await viewModel.load()
        viewModel.providerToDisconnect = .gmail

        // When
        await viewModel.disconnect()

        // Then
        #expect(viewModel.errorMessage != nil)
        // Integration is NOT removed on failure since error is thrown before removeAll
        #expect(viewModel.integrations.count == 1)
    }

    @Test
    func signOutCallsAuthService() async throws {
        // Given
        let mockIntegrationService = MockIntegrationService()
        let mockBackendAPI = MockBackendAPI()
        let mockCalendarSettingsService = MockCalendarSettingsService()
        let mockAuthService = MockAuthService()

        let viewModel = SettingsViewModel(
            integrationService: mockIntegrationService,
            backendAPI: mockBackendAPI,
            calendarSettingsService: mockCalendarSettingsService,
            authService: mockAuthService
        )

        // When
        await viewModel.signOut()

        // Then
        #expect(mockAuthService.signOutCallCount == 1)
        #expect(viewModel.errorMessage == nil)
    }

    @Test
    func providerDisplayNameReturnsProviderNames() async throws {
        // Given
        let mockIntegrationService = MockIntegrationService()
        let mockBackendAPI = MockBackendAPI()
        let mockCalendarSettingsService = MockCalendarSettingsService()
        let mockAuthService = MockAuthService()

        let viewModel = SettingsViewModel(
            integrationService: mockIntegrationService,
            backendAPI: mockBackendAPI,
            calendarSettingsService: mockCalendarSettingsService,
            authService: mockAuthService
        )

        // When/Then
        #expect(viewModel.providerDisplayName(.gmail) == "Gmail")
        #expect(viewModel.providerDisplayName(.googleCalendar) == "Google Calendar")
    }

    @Test
    func updateCalendarCallsService() async throws {
        // Given
        let mockIntegrationService = MockIntegrationService()
        let mockBackendAPI = MockBackendAPI()
        let mockCalendarSettingsService = MockCalendarSettingsService()
        let mockAuthService = MockAuthService()

        let viewModel = SettingsViewModel(
            integrationService: mockIntegrationService,
            backendAPI: mockBackendAPI,
            calendarSettingsService: mockCalendarSettingsService,
            authService: mockAuthService
        )

        // Set up calendars and selection
        let calendar = CalendarInfo(id: "cal_123", name: "Work Calendar", isPrimary: true, isSelected: true)
        viewModel.calendars = [calendar]
        viewModel.selectedCalendarId = "cal_123"

        // When
        await viewModel.updateDefaultCalendar()

        // Then
        #expect(mockCalendarSettingsService.updateDefaultCalendarCallCount == 1)
        #expect(mockCalendarSettingsService.lastUpdateCalendarId == "cal_123")
        #expect(mockCalendarSettingsService.lastUpdateCalendarName == "Work Calendar")
        #expect(viewModel.errorMessage == nil)
    }

    @Test
    func updateAllDayDisplayModeSavesPreference() async throws {
        let mockCalendarSettingsService = MockCalendarSettingsService()
        let viewModel = SettingsViewModel(
            integrationService: MockIntegrationService(),
            backendAPI: MockBackendAPI(),
            calendarSettingsService: mockCalendarSettingsService,
            authService: MockAuthService()
        )

        await viewModel.updateAllDayDisplayMode(.day9to5)

        #expect(mockCalendarSettingsService.updateAllDayDisplayPreferenceCallCount == 1)
        #expect(mockCalendarSettingsService.lastAllDayMode == .day9to5)
        #expect(mockCalendarSettingsService.lastCustomStart == nil)
        #expect(mockCalendarSettingsService.lastCustomEnd == nil)
        #expect(viewModel.allDayDisplayMode == .day9to5)
        #expect(viewModel.errorMessage == nil)
    }

    @Test
    func updateAllDayCustomTimesRejectsInvalidRange() async throws {
        let mockCalendarSettingsService = MockCalendarSettingsService()
        let viewModel = SettingsViewModel(
            integrationService: MockIntegrationService(),
            backendAPI: MockBackendAPI(),
            calendarSettingsService: mockCalendarSettingsService,
            authService: MockAuthService()
        )
        viewModel.allDayDisplayMode = .custom
        viewModel.allDayCustomStart = Calendar.current.date(
            bySettingHour: 17, minute: 0, second: 0, of: Date()
        ) ?? Date()
        viewModel.allDayCustomEnd = Calendar.current.date(
            bySettingHour: 9, minute: 0, second: 0, of: Date()
        ) ?? Date()

        await viewModel.updateAllDayCustomTimes()

        #expect(mockCalendarSettingsService.updateAllDayDisplayPreferenceCallCount == 0)
        #expect(viewModel.allDayCustomError == String(localized: "settings.date_only_custom_error"))
    }

    @Test
    func updateAllDayCustomTimesSavesValidRange() async throws {
        let mockCalendarSettingsService = MockCalendarSettingsService()
        let viewModel = SettingsViewModel(
            integrationService: MockIntegrationService(),
            backendAPI: MockBackendAPI(),
            calendarSettingsService: mockCalendarSettingsService,
            authService: MockAuthService()
        )
        viewModel.allDayDisplayMode = .custom
        viewModel.allDayCustomStart = Calendar.current.date(
            bySettingHour: 10, minute: 0, second: 0, of: Date()
        ) ?? Date()
        viewModel.allDayCustomEnd = Calendar.current.date(
            bySettingHour: 14, minute: 30, second: 0, of: Date()
        ) ?? Date()

        await viewModel.updateAllDayCustomTimes()

        #expect(mockCalendarSettingsService.updateAllDayDisplayPreferenceCallCount == 1)
        #expect(mockCalendarSettingsService.lastAllDayMode == .custom)
        #expect(mockCalendarSettingsService.lastCustomStart == "10:00")
        #expect(mockCalendarSettingsService.lastCustomEnd == "14:30")
        #expect(viewModel.allDayCustomError == nil)
    }

    @Test
    func loadGroupsFoldersForConnectedEmailProviders() async {
        let integrations = MockIntegrationService()
        integrations.fetchIntegrationsResult = .success([integration(.gmail), integration(.outlook)])
        let backend = MockBackendAPI()
        backend.emailFoldersByProvider["gmail"] = .success([folder(included: false)])
        backend.emailFoldersByProvider["outlook"] = .success([])
        let viewModel = SettingsViewModel(
            integrationService: integrations,
            backendAPI: backend,
            calendarSettingsService: MockCalendarSettingsService(),
            authService: MockAuthService()
        )

        await viewModel.load()

        #expect(backend.listEmailFoldersCalls == ["gmail", "outlook"])
        #expect(viewModel.folders(for: .gmail).count == 1)
        #expect(viewModel.folders(for: .outlook).isEmpty)
    }

    @Test
    func folderLoadFailureIsScopedAndRetryRecovers() async {
        let integrations = MockIntegrationService()
        integrations.fetchIntegrationsResult = .success([integration(.gmail)])
        let backend = MockBackendAPI()
        backend.emailFoldersByProvider["gmail"] = .failure(
            NSError(domain: "test", code: 1, userInfo: [NSLocalizedDescriptionKey: "Folders unavailable"])
        )
        let viewModel = SettingsViewModel(
            integrationService: integrations,
            backendAPI: backend,
            calendarSettingsService: MockCalendarSettingsService(),
            authService: MockAuthService()
        )

        await viewModel.load()

        #expect(viewModel.errorMessage == nil)
        #expect(viewModel.folderLoadErrors[.gmail] == "Folders unavailable")
        backend.emailFoldersByProvider["gmail"] = .success([folder(included: true)])

        await viewModel.reloadEmailFolders(provider: .gmail)

        #expect(viewModel.folderLoadErrors[.gmail] == nil)
        #expect(viewModel.folders(for: .gmail).first?.isIncluded == true)
    }

    @Test
    func folderUpdateIsOptimisticAndOnlyMarksThatRowBusy() async {
        let backend = MockBackendAPI()
        backend.updateEmailFolderDelayNanoseconds = 50_000_000
        backend.updateEmailFolderResult = .success(folder(included: true))
        let viewModel = SettingsViewModel(backendAPI: backend)
        viewModel.emailFolders[.gmail] = [folder(included: false), folder(id: "folder-2", included: true)]

        let task = Task { await viewModel.updateFolder(provider: .gmail, folderId: "folder-1", isIncluded: true) }
        await Task.yield()

        #expect(viewModel.folders(for: .gmail).first?.isIncluded == true)
        #expect(viewModel.updatingFolderIds == ["folder-1"])
        #expect(!viewModel.updatingFolderIds.contains("folder-2"))
        await task.value
        #expect(viewModel.updatingFolderIds.isEmpty)
    }

    @Test
    func failedFolderUpdateRollsBackAndRetryUsesRequestedState() async {
        let backend = MockBackendAPI()
        backend.updateEmailFolderResult = .failure(NSError(domain: "test", code: 1, userInfo: [NSLocalizedDescriptionKey: "Save failed"]))
        let viewModel = SettingsViewModel(backendAPI: backend)
        viewModel.emailFolders[.gmail] = [folder(included: false)]

        await viewModel.updateFolder(provider: .gmail, folderId: "folder-1", isIncluded: true)

        #expect(viewModel.folders(for: .gmail).first?.isIncluded == false)
        #expect(viewModel.folderErrors["folder-1"]?.message == "Save failed")
        backend.updateEmailFolderResult = .success(folder(included: true))

        await viewModel.retryFolderUpdate(provider: .gmail, folderId: "folder-1")

        #expect(backend.updateEmailFolderCalls.count == 2)
        #expect(backend.updateEmailFolderCalls.last?.isIncluded == true)
        #expect(viewModel.folders(for: .gmail).first?.isIncluded == true)
        #expect(viewModel.folderErrors["folder-1"] == nil)
    }
}
