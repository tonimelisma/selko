//
//  AuthService.swift
//  Selko
//
//  Created by Claude on 1/26/26.
//

import Foundation
import Supabase
import Combine

protocol AuthServiceProtocol: Sendable {
    func signIn(email: String, password: String) async throws -> User
    func signUp(email: String, password: String) async throws -> User
    func signOut() async throws
    func getCurrentUser() async -> User?
    var authStatePublisher: AnyPublisher<AuthState, Never> { get }
}

final class AuthService: AuthServiceProtocol, @unchecked Sendable {
    private let supabase: SupabaseClient
    private let authStateSubject = CurrentValueSubject<AuthState, Never>(.unknown)

    var authStatePublisher: AnyPublisher<AuthState, Never> {
        authStateSubject.eraseToAnyPublisher()
    }

    init(supabase: SupabaseClient) {
        self.supabase = supabase
        setupAuthListener()
    }

    private func setupAuthListener() {
        Task {
            for await (event, session) in supabase.auth.authStateChanges {
                await MainActor.run {
                    switch event {
                    case .initialSession, .signedIn:
                        if let session = session {
                            let user = User(
                                id: session.user.id,
                                email: session.user.email ?? "",
                                createdAt: session.user.createdAt
                            )
                            authStateSubject.send(.authenticated(user))
                        } else {
                            authStateSubject.send(.unauthenticated)
                        }
                    case .signedOut:
                        authStateSubject.send(.unauthenticated)
                    default:
                        break
                    }
                }
            }
        }
    }

    func signIn(email: String, password: String) async throws -> User {
        do {
            let session = try await supabase.auth.signIn(email: email, password: password)
            return User(
                id: session.user.id,
                email: session.user.email ?? email,
                createdAt: session.user.createdAt
            )
        } catch let error as Auth.AuthError {
            throw mapSupabaseError(error)
        } catch {
            throw AppAuthError.unknown(error.localizedDescription)
        }
    }

    func signUp(email: String, password: String) async throws -> User {
        do {
            let response = try await supabase.auth.signUp(email: email, password: password)
            let supabaseUser = response.user
            return User(
                id: supabaseUser.id,
                email: supabaseUser.email ?? email,
                createdAt: supabaseUser.createdAt
            )
        } catch let error as Auth.AuthError {
            throw mapSupabaseError(error)
        } catch {
            throw AppAuthError.unknown(error.localizedDescription)
        }
    }

    func signOut() async throws {
        try await supabase.auth.signOut()
    }

    func getCurrentUser() async -> User? {
        guard let session = try? await supabase.auth.session else {
            return nil
        }
        return User(
            id: session.user.id,
            email: session.user.email ?? "",
            createdAt: session.user.createdAt
        )
    }

    private func mapSupabaseError(_ error: Auth.AuthError) -> AppAuthError {
        // Map Supabase auth errors to our app's error types
        let message = error.localizedDescription.lowercased()
        if message.contains("invalid") || message.contains("credentials") {
            return .invalidCredentials
        } else if message.contains("already") || message.contains("exists") {
            return .emailAlreadyExists
        } else if message.contains("weak") || message.contains("password") {
            return .weakPassword
        } else {
            return .serverError(error.localizedDescription)
        }
    }
}
