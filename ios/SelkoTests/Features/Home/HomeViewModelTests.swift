//
//  HomeViewModelTests.swift
//  SelkoTests
//
//  Created by Claude on 1/26/26.
//

import Foundation
import Testing
@testable import iOS

@MainActor
struct HomeViewModelTests {
    @Test
    func loadUserSetsUserEmail() async throws {
        // Given
        let mockAuthService = MockAuthService()
        let expectedUser = User(id: UUID(), email: "test@example.com")
        mockAuthService.currentUser = expectedUser

        let viewModel = HomeViewModel(authService: mockAuthService)

        // When
        await viewModel.loadUser()

        // Then
        #expect(viewModel.userEmail == "test@example.com")
        #expect(viewModel.isLoading == false)
    }

    @Test
    func loadUserWithNoUserSetsEmptyEmail() async throws {
        // Given
        let mockAuthService = MockAuthService()
        mockAuthService.currentUser = nil

        let viewModel = HomeViewModel(authService: mockAuthService)

        // When
        await viewModel.loadUser()

        // Then
        #expect(viewModel.userEmail == "")
        #expect(viewModel.isLoading == false)
    }

    @Test
    func signOutCallsAuthService() async throws {
        // Given
        let mockAuthService = MockAuthService()
        let viewModel = HomeViewModel(authService: mockAuthService)

        // When
        await viewModel.signOut()

        // Then
        #expect(mockAuthService.signOutCallCount == 1)
        #expect(viewModel.errorMessage == nil)
    }

    @Test
    func signOutErrorSetsErrorMessage() async throws {
        // Given
        let mockAuthService = MockAuthService()
        mockAuthService.signOutError = AppAuthError.networkError

        let viewModel = HomeViewModel(authService: mockAuthService)

        // When
        await viewModel.signOut()

        // Then
        #expect(viewModel.errorMessage != nil)
    }
}
