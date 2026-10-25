//
//  GoogleConnectionTests.swift
//  SelkoTests
//

import Foundation
import Testing
@testable import iOS

@MainActor
struct GoogleConnectionTests {
    private func row(_ provider: IntegrationProvider, _ status: IntegrationStatus = .active) -> Integration {
        Integration(
            id: UUID(),
            userId: UUID(),
            provider: provider,
            status: status,
            providerEmail: "user@gmail.com",
            scopes: [],
            lastSyncAt: nil,
            createdAt: nil,
            updatedAt: nil
        )
    }

    @Test
    func noGoogleRowsIsNotConnectedEvenWithOutlook() {
        let google = GoogleConnection(integrations: [row(.outlook)])
        #expect(google.state == .notConnected)
        #expect(google.rows.isEmpty)
    }

    @Test
    func bothActiveRowsAreConnected() {
        let google = GoogleConnection(integrations: [row(.gmail), row(.googleCalendar)])
        #expect(google.state == .connected)
        #expect(google.email == "user@gmail.com")
    }

    @Test
    func oneActiveRowNamesTheMissingProduct() {
        #expect(GoogleConnection(integrations: [row(.gmail)]).state == .partial(missing: .googleCalendar))
        #expect(GoogleConnection(integrations: [row(.googleCalendar)]).state == .partial(missing: .gmail))
    }

    @Test
    func anyInactiveRowNeedsReconnect() {
        #expect(
            GoogleConnection(integrations: [row(.gmail), row(.googleCalendar, .expired)]).state
                == .needsReconnect(.expired)
        )
        #expect(GoogleConnection(integrations: [row(.gmail, .revoked)]).state == .needsReconnect(.revoked))
    }
}
