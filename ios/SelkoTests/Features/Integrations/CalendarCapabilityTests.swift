//
//  CalendarCapabilityTests.swift
//  SelkoTests
//

import Foundation
import Testing
@testable import iOS

struct CalendarCapabilityTests {
    static let outlookCalendarScope = "https://graph.microsoft.com/Calendars.ReadWrite"

    static func integration(
        _ provider: IntegrationProvider,
        status: IntegrationStatus = .active,
        scopes: [String] = []
    ) -> Integration {
        Integration(
            id: UUID(), userId: UUID(), provider: provider, status: status,
            providerEmail: nil, scopes: scopes, lastSyncAt: nil,
            createdAt: nil, updatedAt: nil
        )
    }

    @Test
    func activeGoogleCalendarCanWrite() {
        #expect(Self.integration(.googleCalendar).canWriteCalendar)
        #expect(!Self.integration(.googleCalendar, status: .expired).canWriteCalendar)
    }

    @Test
    func outlookCanWriteOnlyWithCalendarScope() {
        #expect(Self.integration(.outlook, scopes: [Self.outlookCalendarScope]).canWriteCalendar)
        // Bare and differently-cased scope values also count.
        #expect(Self.integration(.outlook, scopes: ["calendars.readwrite"]).canWriteCalendar)
        #expect(!Self.integration(.outlook, scopes: ["https://graph.microsoft.com/Mail.Read"]).canWriteCalendar)
        #expect(!Self.integration(.outlook, scopes: ["https://graph.microsoft.com/Calendars.Read"]).canWriteCalendar)
        #expect(!Self.integration(.outlook, status: .expired, scopes: [Self.outlookCalendarScope]).canWriteCalendar)
    }

    @Test
    func gmailNeverWritesCalendar() {
        #expect(!Self.integration(.gmail, scopes: [Self.outlookCalendarScope]).canWriteCalendar)
    }

    @Test
    func hasWritableCalendarAcceptsEitherProvider() {
        #expect([Self.integration(.gmail), Self.integration(.googleCalendar)].hasWritableCalendar)
        #expect([Self.integration(.outlook, scopes: [Self.outlookCalendarScope])].hasWritableCalendar)
        #expect(![Self.integration(.outlook)].hasWritableCalendar)
        #expect(![Integration]().hasWritableCalendar)
    }

    @Test
    func outlookWithoutCalendarScopeNeedsReconnect() {
        #expect([Self.integration(.outlook, scopes: ["Mail.Read"])].needsOutlookCalendarReconnect)
        #expect(![Self.integration(.outlook, scopes: [Self.outlookCalendarScope])].needsOutlookCalendarReconnect)
        // An expired Outlook row is a plain reconnect, not a calendar upgrade.
        #expect(![Self.integration(.outlook, status: .expired)].needsOutlookCalendarReconnect)
        #expect(![Self.integration(.googleCalendar)].needsOutlookCalendarReconnect)
    }

    @Test
    func calendarInfoProviderDefaultsToGoogleWhenOmitted() throws {
        let legacy = Data(#"{"id":"primary","name":"Home","is_primary":true,"is_selected":false}"#.utf8)
        let outlook = Data(#"{"id":"outlook:AAMk","name":"Work","is_primary":false,"is_selected":true,"provider":"outlook"}"#.utf8)

        let legacyInfo = try JSONDecoder().decode(CalendarInfo.self, from: legacy)
        let outlookInfo = try JSONDecoder().decode(CalendarInfo.self, from: outlook)

        #expect(legacyInfo.provider == .googleCalendar)
        #expect(outlookInfo.provider == .outlook)
        #expect(outlookInfo.id == "outlook:AAMk")
    }

    // MARK: - Reconnect banner: one action per sign-in

    @Test
    func bothGoogleRowsExpiredOfferOneGoogleAction() {
        // Regression: one button per row offered "Reconnect Gmail" and
        // "Reconnect Google Calendar" for the same Google sign-in.
        let plan = [
            Self.integration(.gmail, status: .expired),
            Self.integration(.googleCalendar, status: .expired),
        ].recoveryPlan

        let google = plan.actions.filter { $0.signIn == .google }
        #expect(google == [RecoveryAction(signIn: .google, isReconnect: true)])
        #expect(google.first?.label == "Reconnect Google")
        #expect(google.first?.authProvider == .gmail)
        #expect(plan.title == .email)
    }

    @Test
    func lapsedGoogleCalendarAloneOffersOnlyGoogle() {
        let plan = [
            Self.integration(.gmail),
            Self.integration(.googleCalendar, status: .revoked),
        ].recoveryPlan

        #expect(plan.actions == [RecoveryAction(signIn: .google, isReconnect: true)])
        #expect(plan.title == .reconnectCalendar)
    }

    @Test
    func outlookWithoutCalendarOffersConnectGoogleOrReconnectOutlook() {
        let plan = [Self.integration(.outlook, scopes: ["Mail.Read"])].recoveryPlan

        #expect(plan.actions.map(\.label) == ["Reconnect Outlook", "Connect Google"])
        #expect(plan.title == .connectCalendar)
    }

    @Test
    func everythingHealthyOffersNothing() {
        let plan = [
            Self.integration(.gmail),
            Self.integration(.googleCalendar),
            Self.integration(.googlePhotos, status: .expired),
        ].recoveryPlan

        #expect(plan.actions.isEmpty)
        #expect(plan.title == .attention)
    }
}
