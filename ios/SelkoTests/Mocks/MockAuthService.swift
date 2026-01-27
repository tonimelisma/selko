//
//  MockAuthService.swift
//  SelkoTests
//
//  Created by Claude on 1/26/26.
//

import Foundation
import Combine
@testable import iOS

final class MockAuthService: AuthServiceProtocol, @unchecked Sendable {
    var signInResult: Result<User, Error> = .success(.mock)
    var signUpResult: Result<User, Error> = .success(.mock)
    var signOutError: Error?
    var currentUser: User?

    var signInCallCount = 0
    var signUpCallCount = 0
    var signOutCallCount = 0
    var lastSignInEmail: String?
    var lastSignInPassword: String?
    var lastSignUpEmail: String?
    var lastSignUpPassword: String?

    private let authStateSubject = CurrentValueSubject<AuthState, Never>(.unauthenticated)

    var authStatePublisher: AnyPublisher<AuthState, Never> {
        authStateSubject.eraseToAnyPublisher()
    }

    func signIn(email: String, password: String) async throws -> User {
        signInCallCount += 1
        lastSignInEmail = email
        lastSignInPassword = password

        switch signInResult {
        case .success(let user):
            authStateSubject.send(.authenticated(user))
            return user
        case .failure(let error):
            throw error
        }
    }

    func signUp(email: String, password: String) async throws -> User {
        signUpCallCount += 1
        lastSignUpEmail = email
        lastSignUpPassword = password

        switch signUpResult {
        case .success(let user):
            return user
        case .failure(let error):
            throw error
        }
    }

    func signOut() async throws {
        signOutCallCount += 1
        if let error = signOutError {
            throw error
        }
        authStateSubject.send(.unauthenticated)
    }

    func getCurrentUser() async -> User? {
        return currentUser
    }

    func setAuthState(_ state: AuthState) {
        authStateSubject.send(state)
    }
}
