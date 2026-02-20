//
//  DeepLinkTests.swift
//  SelkoTests
//

import Foundation
import Testing
@testable import iOS

struct DeepLinkParsingTests {
    // MARK: - Tab Deep Links

    @Test
    func parseReviewTabURL() {
        let url = URL(string: "selko://review")!
        let result = AppRouter.parseDeepLink(url)
        #expect(result == .tab(.review))
    }

    @Test
    func parseHistoryTabURL() {
        let url = URL(string: "selko://history")!
        let result = AppRouter.parseDeepLink(url)
        #expect(result == .tab(.history))
    }

    @Test
    func parseSettingsTabURL() {
        let url = URL(string: "selko://settings")!
        let result = AppRouter.parseDeepLink(url)
        #expect(result == .tab(.settings))
    }

    // MARK: - Event Detail Deep Links

    @Test
    func parseEventDetailURL() {
        let eventId = UUID()
        let url = URL(string: "selko://event/\(eventId.uuidString)")!
        let result = AppRouter.parseDeepLink(url)
        #expect(result == .eventDetail(eventId))
    }

    @Test
    func parseEventDetailURLWithLowercaseUUID() {
        let eventId = UUID()
        let url = URL(string: "selko://event/\(eventId.uuidString.lowercased())")!
        let result = AppRouter.parseDeepLink(url)
        #expect(result == .eventDetail(eventId))
    }

    // MARK: - Invalid URLs

    @Test
    func parseInvalidSchemeReturnsNil() {
        let url = URL(string: "https://review")!
        let result = AppRouter.parseDeepLink(url)
        #expect(result == nil)
    }

    @Test
    func parseUnknownHostReturnsNil() {
        let url = URL(string: "selko://unknown")!
        let result = AppRouter.parseDeepLink(url)
        #expect(result == nil)
    }

    @Test
    func parseEventWithoutIdReturnsNil() {
        let url = URL(string: "selko://event")!
        let result = AppRouter.parseDeepLink(url)
        #expect(result == nil)
    }

    @Test
    func parseEventWithInvalidIdReturnsNil() {
        let url = URL(string: "selko://event/not-a-uuid")!
        let result = AppRouter.parseDeepLink(url)
        #expect(result == nil)
    }

    @Test
    func parseEmptyHostReturnsNil() {
        let url = URL(string: "selko://")!
        let result = AppRouter.parseDeepLink(url)
        #expect(result == nil)
    }
}

@MainActor
struct AppRouterDeepLinkTests {
    @Test
    func handleReviewDeepLinkSetsTab() {
        let router = AppRouter(authService: MockAuthService())
        let url = URL(string: "selko://review")!

        router.handleDeepLink(url)

        #expect(router.selectedTab == .review)
        #expect(router.pendingEventId == nil)
    }

    @Test
    func handleHistoryDeepLinkSetsTab() {
        let router = AppRouter(authService: MockAuthService())
        let url = URL(string: "selko://history")!

        router.handleDeepLink(url)

        #expect(router.selectedTab == .history)
        #expect(router.pendingEventId == nil)
    }

    @Test
    func handleSettingsDeepLinkSetsTab() {
        let router = AppRouter(authService: MockAuthService())
        let url = URL(string: "selko://settings")!

        router.handleDeepLink(url)

        #expect(router.selectedTab == .settings)
        #expect(router.pendingEventId == nil)
    }

    @Test
    func handleEventDeepLinkSetsTabAndPendingEventId() {
        let router = AppRouter(authService: MockAuthService())
        let eventId = UUID()
        let url = URL(string: "selko://event/\(eventId.uuidString)")!

        router.handleDeepLink(url)

        #expect(router.selectedTab == .review)
        #expect(router.pendingEventId == eventId)
    }

    @Test
    func handleInvalidDeepLinkDoesNotChangeState() {
        let router = AppRouter(authService: MockAuthService())
        router.selectedTab = .settings
        let url = URL(string: "selko://invalid")!

        router.handleDeepLink(url)

        #expect(router.selectedTab == .settings)
        #expect(router.pendingEventId == nil)
    }

    @Test
    func handleTabDeepLinkClearsPendingEventId() {
        let router = AppRouter(authService: MockAuthService())
        router.pendingEventId = UUID()
        let url = URL(string: "selko://history")!

        router.handleDeepLink(url)

        #expect(router.selectedTab == .history)
        #expect(router.pendingEventId == nil)
    }
}
