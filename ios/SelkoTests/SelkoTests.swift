//
//  SelkoTests.swift
//  SelkoTests
//
//  Created by Toni Melisma on 1/26/26.
//

import Foundation
import Testing
@testable import iOS

struct UserTests {
    @Test
    func userInitializesCorrectly() {
        // Given
        let id = UUID()
        let email = "test@example.com"
        let createdAt = Date()

        // When
        let user = User(id: id, email: email, createdAt: createdAt)

        // Then
        #expect(user.id == id)
        #expect(user.email == email)
        #expect(user.createdAt == createdAt)
    }

    @Test
    func userMockHasValidData() {
        // When
        let user = User.mock

        // Then
        #expect(user.email == "test@example.com")
        #expect(user.createdAt != nil)
    }
}

struct AuthStateTests {
    @Test
    func authStatesAreEquatable() {
        // Given
        let user = User.mock

        // Then
        #expect(AuthState.unknown == AuthState.unknown)
        #expect(AuthState.unauthenticated == AuthState.unauthenticated)
        #expect(AuthState.authenticated(user) == AuthState.authenticated(user))
    }
}

struct AppAuthErrorTests {
    @Test
    func authErrorsHaveDescriptions() {
        // Then
        #expect(AppAuthError.invalidCredentials.errorDescription != nil)
        #expect(AppAuthError.emailAlreadyExists.errorDescription != nil)
        #expect(AppAuthError.weakPassword.errorDescription != nil)
        #expect(AppAuthError.networkError.errorDescription != nil)
        #expect(AppAuthError.serverError("test").errorDescription != nil)
        #expect(AppAuthError.unknown("test").errorDescription != nil)
    }
}
