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

    /// UI tests pass this to guarantee a launch starts signed out.
    ///
    /// `app.launch()` does not reset app state, so a session persisted by an
    /// earlier test leaks into the next one: the login screen never appears,
    /// the sign-in step is skipped, and the run fails somewhere later with a
    /// misleading message. Resetting at startup makes each launch deterministic
    /// instead of dependent on test execution order.
    static let resetSessionArgument = "--selko-reset-session"

    /// Session handed in by the UI test harness; see `applyExternalSession`.
    static let testAccessTokenVariable = "SELKO_TEST_ACCESS_TOKEN"
    static let testRefreshTokenVariable = "SELKO_TEST_REFRESH_TOKEN"

    init(authService: AuthServiceProtocol? = nil) {
        self.authService = authService ?? DependencyContainer.shared.authService

        guard ProcessInfo.processInfo.arguments.contains(Self.resetSessionArgument) else {
            observeAuthState()
            return
        }

        // Sign out *before* observing auth state, and stay in the loading state
        // until it finishes. Doing the sign-out concurrently with observation
        // let it land after the test had already signed in, silently revoking
        // the fresh session -- which surfaced as "Main tab view did not appear
        // after signing in" and looked like a slow login rather than a race.
        isLoading = true
        let service = self.authService
        let environment = ProcessInfo.processInfo.environment
        let accessToken = environment[Self.testAccessTokenVariable]
        let refreshToken = environment[Self.testRefreshTokenVariable]
        Task { @MainActor [weak self] in
            try? await service.signOut()
            // A session supplied by the test harness is installed before auth
            // state is observed, so the app comes up authenticated without the
            // login form being driven by simulated typing.
            if let accessToken, let refreshToken,
               !accessToken.isEmpty, !refreshToken.isEmpty {
                try? await service.applyExternalSession(
                    accessToken: accessToken,
                    refreshToken: refreshToken
                )
            }
            self?.observeAuthState()
        }
    }

    private func observeAuthState() {
        authService.authStatePublisher
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
            // Live invalidation wiring (C6): establish the private Broadcast
            // channel for this user. The view models catch up from the
            // database on scene-active via catchUp(); the channel is the hint.
            Task { @MainActor in
                await DependencyContainer.shared.liveUpdateService.start(userId: user.id)
            }
        case .unauthenticated:
            isLoading = false
            isAuthenticated = false
            userEmail = ""
            Task { @MainActor in
                await DependencyContainer.shared.liveUpdateService.stop()
            }
        }
    }
}
