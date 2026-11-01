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

    // MARK: - Connection banner: name the account that broke

    @Test
    func googleSignedOutBesideMailOnlyOutlookNamesGoogleOnly() {
        // Regression: production showed "Reconnect your calendar" with equal
        // Outlook and Google buttons, although Gmail was down too and Outlook
        // had never been the user's calendar.
        let plan = [
            Self.integration(.gmail, status: .expired),
            Self.integration(.googleCalendar, status: .expired),
            Self.integration(.outlook, scopes: ["Mail.Read"]),
        ].recoveryPlan

        #expect(plan?.kind == .signedOut(.google, RecoveryPlan.Lost(mail: true, calendar: true)))
        #expect(plan?.title == "Reconnect your Google account")
        #expect(plan?.message.contains("can’t read new Gmail or add events to Google Calendar") == true)
        #expect(plan?.actions == [RecoveryAction(signIn: .google, verb: .reconnect)])
        #expect(plan?.actions.first?.label == "Reconnect Google")
        #expect(plan?.actions.first?.authProvider == .gmail)
    }

    @Test
    func lapsedGoogleCalendarAloneSaysCalendar() {
        let plan = [
            Self.integration(.gmail),
            Self.integration(.googleCalendar, status: .revoked),
        ].recoveryPlan

        #expect(plan?.kind == .signedOut(.google, RecoveryPlan.Lost(mail: false, calendar: true)))
        #expect(plan?.actions.count == 1)
    }

    @Test
    func lapsedGoogleCalendarIsQuietWhileOutlookCalendarWorks() {
        let plan = [
            Self.integration(.outlook, scopes: ["Calendars.ReadWrite"]),
            Self.integration(.googleCalendar, status: .expired),
        ].recoveryPlan

        #expect(plan == nil)
    }

    @Test
    func bothSignInsLapsedOffersBoth() {
        let plan = [
            Self.integration(.gmail, status: .expired),
            Self.integration(.outlook, status: .expired),
        ].recoveryPlan

        #expect(plan?.kind == .accounts)
        #expect(plan?.actions.map(\.label) == ["Reconnect Google", "Reconnect Outlook"])
    }

    @Test
    func mailOnlyOutlookOffersOutlookCalendarOnly() {
        let plan = [Self.integration(.outlook, scopes: ["Mail.Read"])].recoveryPlan

        #expect(plan?.kind == .connectCalendar)
        #expect(plan?.actions.map(\.label) == ["Connect Outlook Calendar"])
    }

    @Test
    func everythingHealthyOffersNothing() {
        let plan = [
            Self.integration(.gmail),
            Self.integration(.googleCalendar),
            Self.integration(.googlePhotos, status: .expired),
        ].recoveryPlan

        #expect(plan == nil)
    }
}
