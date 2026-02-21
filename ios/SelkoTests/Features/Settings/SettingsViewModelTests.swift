//
//  SettingsViewModelTests.swift
//  SelkoTests
//

import Foundation
import Testing
@testable import iOS

@MainActor
struct SettingsViewModelTests {
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
    func loadFetchesGooglePhotosIntegration() async throws {
        // Given
        let mockIntegrationService = MockIntegrationService()
        let mockBackendAPI = MockBackendAPI()
        let mockCalendarSettingsService = MockCalendarSettingsService()
        let mockAuthService = MockAuthService()

        let photosIntegration = Integration(
            id: UUID(),
            userId: UUID(),
            provider: .googlePhotos,
            status: .active,
            providerEmail: "user@gmail.com",
            scopes: ["https://www.googleapis.com/auth/photoslibrary.readonly"],
            lastSyncAt: Date(),
            createdAt: Date(),
            updatedAt: Date()
        )
        mockIntegrationService.fetchIntegrationsResult = .success([photosIntegration])

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
        #expect(viewModel.integrations.first?.provider == .googlePhotos)
        #expect(viewModel.integration(for: .googlePhotos)?.isActive == true)
        #expect(viewModel.isLoading == false)
        #expect(viewModel.errorMessage == nil)
    }

    @Test
    func providerDisplayNameReturnsGooglePhotos() async throws {
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
        #expect(viewModel.providerDisplayName(.googlePhotos) == "Google Photos")
        #expect(viewModel.providerDisplayName(.gmail) == "Gmail")
        #expect(viewModel.providerDisplayName(.googleCalendar) == "Google Calendar")
    }

    @Test
    func disconnectGooglePhotosRemovesIntegration() async throws {
        // Given
        let mockIntegrationService = MockIntegrationService()
        let mockBackendAPI = MockBackendAPI()
        let mockCalendarSettingsService = MockCalendarSettingsService()
        let mockAuthService = MockAuthService()

        let photosIntegration = Integration(
            id: UUID(),
            userId: UUID(),
            provider: .googlePhotos,
            status: .active,
            providerEmail: "user@gmail.com",
            scopes: [],
            lastSyncAt: nil,
            createdAt: Date(),
            updatedAt: Date()
        )
        mockIntegrationService.fetchIntegrationsResult = .success([photosIntegration])

        let viewModel = SettingsViewModel(
            integrationService: mockIntegrationService,
            backendAPI: mockBackendAPI,
            calendarSettingsService: mockCalendarSettingsService,
            authService: mockAuthService
        )

        await viewModel.load()
        #expect(viewModel.integrations.count == 1)

        // Set up the provider to disconnect
        viewModel.providerToDisconnect = .googlePhotos

        // When
        await viewModel.disconnect()

        // Then
        #expect(viewModel.integrations.isEmpty)
        #expect(mockIntegrationService.deleteIntegrationCallCount == 1)
        #expect(mockIntegrationService.lastDeletedProvider == .googlePhotos)
        #expect(viewModel.errorMessage == nil)
    }

    @Test
    func loadMultipleIntegrationsIncludingPhotos() async throws {
        // Given
        let mockIntegrationService = MockIntegrationService()
        let mockBackendAPI = MockBackendAPI()
        let mockCalendarSettingsService = MockCalendarSettingsService()
        let mockAuthService = MockAuthService()

        let userId = UUID()
        let gmailIntegration = Integration(
            id: UUID(), userId: userId, provider: .gmail, status: .active,
            providerEmail: "user@gmail.com", scopes: [], lastSyncAt: nil,
            createdAt: Date(), updatedAt: Date()
        )
        let calendarIntegration = Integration(
            id: UUID(), userId: userId, provider: .googleCalendar, status: .active,
            providerEmail: "user@gmail.com", scopes: [], lastSyncAt: nil,
            createdAt: Date(), updatedAt: Date()
        )
        let photosIntegration = Integration(
            id: UUID(), userId: userId, provider: .googlePhotos, status: .active,
            providerEmail: "user@gmail.com", scopes: [], lastSyncAt: nil,
            createdAt: Date(), updatedAt: Date()
        )
        mockIntegrationService.fetchIntegrationsResult = .success([
            gmailIntegration, calendarIntegration, photosIntegration
        ])

        let viewModel = SettingsViewModel(
            integrationService: mockIntegrationService,
            backendAPI: mockBackendAPI,
            calendarSettingsService: mockCalendarSettingsService,
            authService: mockAuthService
        )

        // When
        await viewModel.load()

        // Then
        #expect(viewModel.integrations.count == 3)
        #expect(viewModel.integration(for: .gmail)?.isActive == true)
        #expect(viewModel.integration(for: .googleCalendar)?.isActive == true)
        #expect(viewModel.integration(for: .googlePhotos)?.isActive == true)
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
}
