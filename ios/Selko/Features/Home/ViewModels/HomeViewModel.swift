//
//  HomeViewModel.swift
//  Selko
//
//  Created by Claude on 1/26/26.
//

import Foundation

@MainActor
@Observable
final class HomeViewModel {
    var userEmail: String = ""
    var isLoading = false
    var errorMessage: String?

    private let authService: AuthServiceProtocol

    init(authService: AuthServiceProtocol? = nil) {
        self.authService = authService ?? DependencyContainer.shared.authService
    }

    func loadUser() async {
        isLoading = true
        if let user = await authService.getCurrentUser() {
            userEmail = user.email
        }
        isLoading = false
    }

    func signOut() async {
        do {
            try await authService.signOut()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
