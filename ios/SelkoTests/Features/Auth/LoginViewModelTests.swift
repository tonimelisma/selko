//
//  LoginViewModelTests.swift
//  SelkoTests
//
//  Created by Claude on 1/26/26.
//

import Testing
@testable import iOS

@MainActor
struct LoginViewModelTests {
    @Test
    func loginWithValidCredentialsSucceeds() async throws {
        // Given
        let mockAuthService = MockAuthService()
        let expectedUser = User.mock
        mockAuthService.signInResult = .success(expectedUser)

        let viewModel = LoginViewModel(authService: mockAuthService)
        viewModel.email = "test@example.com"
        viewModel.password = "password123"

        // When
        await viewModel.login()

        // Then
        #expect(viewModel.errorMessage == nil)
        #expect(mockAuthService.signInCallCount == 1)
        #expect(mockAuthService.lastSignInEmail == "test@example.com")
        #expect(mockAuthService.lastSignInPassword == "password123")
        #expect(viewModel.isLoading == false)
    }

    @Test
    func loginWithEmptyEmailShowsError() async throws {
        // Given
        let mockAuthService = MockAuthService()
        let viewModel = LoginViewModel(authService: mockAuthService)
        viewModel.email = ""
        viewModel.password = "password123"

        // When
        await viewModel.login()

        // Then
        #expect(viewModel.errorMessage == "Email is required")
        #expect(mockAuthService.signInCallCount == 0)
    }

    @Test
    func loginWithEmptyPasswordShowsError() async throws {
        // Given
        let mockAuthService = MockAuthService()
        let viewModel = LoginViewModel(authService: mockAuthService)
        viewModel.email = "test@example.com"
        viewModel.password = ""

        // When
        await viewModel.login()

        // Then
        #expect(viewModel.errorMessage == "Password is required")
        #expect(mockAuthService.signInCallCount == 0)
    }

    @Test
    func loginWithInvalidEmailShowsError() async throws {
        // Given
        let mockAuthService = MockAuthService()
        let viewModel = LoginViewModel(authService: mockAuthService)
        viewModel.email = "notanemail"
        viewModel.password = "password123"

        // When
        await viewModel.login()

        // Then
        #expect(viewModel.errorMessage == "Please enter a valid email address")
        #expect(mockAuthService.signInCallCount == 0)
    }

    @Test
    func loginWhenServiceFailsShowsError() async throws {
        // Given
        let mockAuthService = MockAuthService()
        mockAuthService.signInResult = .failure(AppAuthError.invalidCredentials)

        let viewModel = LoginViewModel(authService: mockAuthService)
        viewModel.email = "test@example.com"
        viewModel.password = "password123"

        // When
        await viewModel.login()

        // Then
        #expect(viewModel.errorMessage != nil)
        #expect(viewModel.isLoading == false)
    }

    @Test
    func loginTrimsWhitespaceFromEmail() async throws {
        // Given
        let mockAuthService = MockAuthService()
        let viewModel = LoginViewModel(authService: mockAuthService)
        viewModel.email = "   "
        viewModel.password = "password123"

        // When
        await viewModel.login()

        // Then
        #expect(viewModel.errorMessage == "Email is required")
        #expect(mockAuthService.signInCallCount == 0)
    }
}
