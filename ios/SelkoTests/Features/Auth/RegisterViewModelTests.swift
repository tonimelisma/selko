//
//  RegisterViewModelTests.swift
//  SelkoTests
//
//  Created by Claude on 1/26/26.
//

import Testing
@testable import iOS

@MainActor
struct RegisterViewModelTests {
    @Test
    func registerWithValidDataSucceeds() async throws {
        // Given
        let mockAuthService = MockAuthService()
        let expectedUser = User.mock
        mockAuthService.signUpResult = .success(expectedUser)

        let viewModel = RegisterViewModel(authService: mockAuthService)
        viewModel.email = "test@example.com"
        viewModel.password = "password123"
        viewModel.confirmPassword = "password123"

        // When
        await viewModel.register()

        // Then
        #expect(viewModel.errorMessage == nil)
        #expect(viewModel.registrationComplete == true)
        #expect(mockAuthService.signUpCallCount == 1)
        #expect(mockAuthService.lastSignUpEmail == "test@example.com")
        #expect(mockAuthService.lastSignUpPassword == "password123")
    }

    @Test
    func registerWithEmptyEmailShowsError() async throws {
        // Given
        let mockAuthService = MockAuthService()
        let viewModel = RegisterViewModel(authService: mockAuthService)
        viewModel.email = ""
        viewModel.password = "password123"
        viewModel.confirmPassword = "password123"

        // When
        await viewModel.register()

        // Then
        #expect(viewModel.errorMessage == "Email is required")
        #expect(mockAuthService.signUpCallCount == 0)
    }

    @Test
    func registerWithInvalidEmailShowsError() async throws {
        // Given
        let mockAuthService = MockAuthService()
        let viewModel = RegisterViewModel(authService: mockAuthService)
        viewModel.email = "notanemail"
        viewModel.password = "password123"
        viewModel.confirmPassword = "password123"

        // When
        await viewModel.register()

        // Then
        #expect(viewModel.errorMessage == "Please enter a valid email address")
        #expect(mockAuthService.signUpCallCount == 0)
    }

    @Test
    func registerWithShortPasswordShowsError() async throws {
        // Given
        let mockAuthService = MockAuthService()
        let viewModel = RegisterViewModel(authService: mockAuthService)
        viewModel.email = "test@example.com"
        viewModel.password = "12345"
        viewModel.confirmPassword = "12345"

        // When
        await viewModel.register()

        // Then
        #expect(viewModel.errorMessage == "Password must be at least 6 characters")
        #expect(mockAuthService.signUpCallCount == 0)
    }

    @Test
    func registerWithMismatchedPasswordsShowsError() async throws {
        // Given
        let mockAuthService = MockAuthService()
        let viewModel = RegisterViewModel(authService: mockAuthService)
        viewModel.email = "test@example.com"
        viewModel.password = "password123"
        viewModel.confirmPassword = "password456"

        // When
        await viewModel.register()

        // Then
        #expect(viewModel.errorMessage == "Passwords do not match")
        #expect(mockAuthService.signUpCallCount == 0)
    }

    @Test
    func registerWhenServiceFailsShowsError() async throws {
        // Given
        let mockAuthService = MockAuthService()
        mockAuthService.signUpResult = .failure(AppAuthError.emailAlreadyExists)

        let viewModel = RegisterViewModel(authService: mockAuthService)
        viewModel.email = "test@example.com"
        viewModel.password = "password123"
        viewModel.confirmPassword = "password123"

        // When
        await viewModel.register()

        // Then
        #expect(viewModel.errorMessage != nil)
        #expect(viewModel.registrationComplete == false)
        #expect(viewModel.isLoading == false)
    }
}
