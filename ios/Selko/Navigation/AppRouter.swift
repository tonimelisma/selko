//
//  AppRouter.swift
//  Selko
//
//  Created by Claude on 1/26/26.
//

import Foundation
import Combine

@MainActor
@Observable
final class AppRouter {
    var isAuthenticated = false
    var isLoading = true

    private let authService: AuthServiceProtocol
    private var cancellables = Set<AnyCancellable>()

    init(authService: AuthServiceProtocol? = nil) {
        self.authService = authService ?? DependencyContainer.shared.authService

        self.authService.authStatePublisher
            .receive(on: DispatchQueue.main)
            .sink { [weak self] state in
                self?.handleAuthStateChange(state)
            }
            .store(in: &cancellables)
    }

    private func handleAuthStateChange(_ state: AuthState) {
        switch state {
        case .unknown:
            isLoading = true
            isAuthenticated = false
        case .authenticated:
            isLoading = false
            isAuthenticated = true
        case .unauthenticated:
            isLoading = false
            isAuthenticated = false
        }
    }
}
