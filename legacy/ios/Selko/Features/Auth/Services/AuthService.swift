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
    /// Installs a session obtained out of band.
    ///
    /// UI tests use this instead of driving the login form. Typing into a field
    /// that is still settling drops characters, which fails sign-in with
    /// "Invalid email or password" and reads as a backend problem; it also
    /// charges every test a full auth round trip. The login *form* is still
    /// covered by tests that exercise it directly.
    func applyExternalSession(accessToken: String, refreshToken: String) async throws
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

    func applyExternalSession(accessToken: String, refreshToken: String) async throws {
        try await supabase.auth.setSession(accessToken: accessToken, refreshToken: refreshToken)
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
                    case .tokenRefreshed:
                        // Private realtime channels authorize per-JWT; re-auth
                        // the socket or it goes deaf ~1h after sign-in.
                        if let token = session?.accessToken {
                            Task { @MainActor in
                                await DependencyContainer.shared.liveUpdateService.refreshAuth(token)
                            }
                        }
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
