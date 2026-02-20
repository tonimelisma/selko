//
//  RegisterViewModel.swift
//  Selko
//
//  Created by Claude on 1/26/26.
//

import Foundation

@MainActor
@Observable
final class RegisterViewModel {
    var email = ""
    var password = ""
    var confirmPassword = ""
    var isLoading = false
    var errorMessage: String?
    var registrationComplete = false

    private let authService: AuthServiceProtocol

    init(authService: AuthServiceProtocol? = nil) {
        self.authService = authService ?? DependencyContainer.shared.authService
    }

    func register() async {
        guard validateInput() else { return }

        isLoading = true
        errorMessage = nil

        do {
            _ = try await authService.signUp(email: email, password: password)
            registrationComplete = true
        } catch let error as AppAuthError {
            errorMessage = error.localizedDescription
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }

    private func validateInput() -> Bool {
        guard !email.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            errorMessage = String(localized: "Email is required")
            return false
        }

        guard email.contains("@") else {
            errorMessage = String(localized: "Please enter a valid email address")
            return false
        }

        guard !password.isEmpty else {
            errorMessage = String(localized: "Password is required")
            return false
        }

        guard password.count >= 6 else {
            errorMessage = String(localized: "Password must be at least 6 characters")
            return false
        }

        guard password == confirmPassword else {
            errorMessage = String(localized: "Passwords do not match")
            return false
        }

        return true
    }
}
