//
//  LoginViewModel.swift
//  Selko
//
//  Created by Claude on 1/26/26.
//

import Foundation

@MainActor
@Observable
final class LoginViewModel {
    var email = ""
    var password = ""
    var isLoading = false
    var errorMessage: String?

    private let authService: AuthServiceProtocol

    init(authService: AuthServiceProtocol? = nil) {
        self.authService = authService ?? DependencyContainer.shared.authService
    }

    func login() async {
        guard validateInput() else { return }

        isLoading = true
        errorMessage = nil

        do {
            _ = try await authService.signIn(email: email, password: password)
        } catch let error as AppAuthError {
            errorMessage = error.localizedDescription
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }

    private func validateInput() -> Bool {
        guard !email.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            errorMessage = "Email is required"
            return false
        }

        guard !password.isEmpty else {
            errorMessage = "Password is required"
            return false
        }

        guard email.contains("@") else {
            errorMessage = "Please enter a valid email address"
            return false
        }

        return true
    }
}
