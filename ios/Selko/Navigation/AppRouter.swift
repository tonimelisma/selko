//
//  AppRouter.swift
//  Selko
//
//  Created by Claude on 1/26/26.
//

import Foundation
import Combine

/// Represents the tabs available in MainTabView.
enum Tab: Int, CaseIterable, Sendable {
    case review = 0
    case history = 1
    case settings = 2
}

/// Represents a parsed deep link destination.
enum DeepLinkDestination: Equatable, Sendable {
    case tab(Tab)
    case eventDetail(UUID)
}

@MainActor
@Observable
final class AppRouter {
    var isAuthenticated = false
    var isLoading = true
    var selectedTab: Tab = .review
    var pendingEventId: UUID?
    var userEmail = ""

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

    /// Parses a `selko://` URL into a `DeepLinkDestination`.
    ///
    /// Supported URLs:
    /// - `selko://review` - Opens the Review tab
    /// - `selko://history` - Opens the History tab
    /// - `selko://settings` - Opens the Settings tab
    /// - `selko://event/{uuid}` - Opens an event detail for the given UUID
    nonisolated static func parseDeepLink(_ url: URL) -> DeepLinkDestination? {
        guard url.scheme == "selko" else { return nil }

        let host = url.host(percentEncoded: false) ?? ""

        switch host {
        case "review":
            return .tab(.review)
        case "history":
            return .tab(.history)
        case "settings":
            return .tab(.settings)
        case "event":
            let pathComponents = url.pathComponents.filter { $0 != "/" }
            guard let idString = pathComponents.first,
                  let eventId = UUID(uuidString: idString) else {
                return nil
            }
            return .eventDetail(eventId)
        default:
            return nil
        }
    }

    /// Handles an incoming deep link URL by updating navigation state.
    func handleDeepLink(_ url: URL) {
        guard let destination = Self.parseDeepLink(url) else { return }

        switch destination {
        case .tab(let tab):
            pendingEventId = nil
            selectedTab = tab
        case .eventDetail(let eventId):
            selectedTab = .review
            pendingEventId = eventId
        }
    }

    private func handleAuthStateChange(_ state: AuthState) {
        switch state {
        case .unknown:
            isLoading = true
            isAuthenticated = false
        case .authenticated(let user):
            isLoading = false
            isAuthenticated = true
            userEmail = user.email
        case .unauthenticated:
            isLoading = false
            isAuthenticated = false
            userEmail = ""
        }
    }
}
