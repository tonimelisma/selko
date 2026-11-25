//
//  Integration.swift
//  Selko
//

import Foundation

enum IntegrationProvider: String, Codable, Sendable {
    case gmail
    case outlook
    case googlePhotos = "google_photos"
    case googleCalendar = "google_calendar"
}

enum IntegrationStatus: String, Codable, Sendable {
    case active
    case expired
    case revoked
    case error
}

enum IntegrationRecoveryStatus: String, Codable, Sendable {
    case pending
    case processing
    case waiting
    case completed
    case completedWithErrors = "completed_with_errors"
    case failed
    case superseded
}

/// Latest Google Calendar reconnect recovery generation.
///
/// Mirrors `public.integration_recoveries`. RLS exposes only the current
/// user's own rows. Email reconnects need no recovery record (they resume
/// from provider cursors), so only `google_calendar` produces one.
struct IntegrationRecovery: Identifiable, Codable, Sendable, Equatable {
    let id: UUID
    let integrationId: UUID
    let userId: UUID
    let provider: IntegrationProvider
    let status: IntegrationRecoveryStatus
    let discoveredCount: Int?
    let completedCount: Int?
    let remainingCount: Int?
    let errorDetail: String?
    let requestedAt: Date?

    enum CodingKeys: String, CodingKey {
        case id
        case integrationId = "integration_id"
        case userId = "user_id"
        case provider
        case status
        case discoveredCount = "discovered_count"
        case completedCount = "completed_count"
        case remainingCount = "remaining_count"
        case errorDetail = "error_detail"
        case requestedAt = "requested_at"
    }

    var isActive: Bool {
        status == .pending || status == .processing || status == .waiting
    }

    var needingAttentionCount: Int {
        max(0, (discoveredCount ?? 0) - (completedCount ?? 0))
    }
}

struct Integration: Identifiable, Codable, Sendable, Equatable {
    let id: UUID
    let userId: UUID
    let provider: IntegrationProvider
    let status: IntegrationStatus
    let providerEmail: String?
    let scopes: [String]
    let lastSyncAt: Date?
    let createdAt: Date?
    let updatedAt: Date?

    enum CodingKeys: String, CodingKey {
        case id
        case userId = "user_id"
        case provider
        case status
        case providerEmail = "provider_email"
        case scopes
        case lastSyncAt = "last_sync_at"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }

    var isActive: Bool {
        status == .active
    }

    /// Whether Selko can write events through this integration. Google
    /// Calendar is writable whenever it is active. The Outlook row is shared
    /// with Outlook mail and is calendar-capable only once its consent
    /// includes `Calendars.ReadWrite`; Outlook rows connected before calendar
    /// support lack that scope until the user reconnects.
    var canWriteCalendar: Bool {
        guard isActive else { return false }
        switch provider {
        case .googleCalendar:
            return true
        case .outlook:
            return scopes.contains { $0.lowercased().hasSuffix("calendars.readwrite") }
        case .gmail, .googlePhotos:
            return false
        }
    }
}

extension Array where Element == Integration {
    /// True when at least one integration can receive approved events:
    /// an active Google Calendar, or an Outlook account with calendar consent.
    var hasWritableCalendar: Bool {
        contains { $0.canWriteCalendar }
    }

    /// True when Outlook is connected for mail but its consent predates
    /// calendar support, so reconnecting Outlook would add calendar writes.
    var needsOutlookCalendarReconnect: Bool {
        contains { $0.provider == .outlook && $0.isActive && !$0.canWriteCalendar }
    }

    /// What the connection banner asks for, written from the user's side:
    /// name the account that stopped working and what it stopped doing, then
    /// offer the one sign-in that fixes it. `nil` when nothing needs the user.
    ///
    /// A lapsed sign-in comes first, because it is the account the user
    /// already chose. Offering a different provider beside it made the banner
    /// a menu of equal-looking buttons for a problem with one answer;
    /// switching providers stays in Settings.
    var recoveryPlan: RecoveryPlan? {
        let rows = filter { $0.provider != .googlePhotos }
        let gmail = rows.first { $0.provider == .gmail }
        let googleCalendar = rows.first { $0.provider == .googleCalendar }
        let outlook = rows.first { $0.provider == .outlook }
        let calendarWritable = rows.hasWritableCalendar

        // A lapsed Google Calendar is not worth a prompt while Outlook Calendar works.
        let googleMailLost = gmail.map { !$0.isActive } ?? false
        let googleCalendarLost = (googleCalendar.map { !$0.isActive } ?? false) && !calendarWritable
        let outlookLost = outlook.map { !$0.isActive } ?? false

        if googleMailLost || googleCalendarLost, outlookLost {
            return RecoveryPlan(kind: .accounts, actions: [
                RecoveryAction(signIn: .google, verb: .reconnect),
                RecoveryAction(signIn: .outlook, verb: .reconnect)
            ])
        }
        if outlookLost, let outlook {
            let hadCalendar = outlook.scopes.contains { $0.lowercased().hasSuffix("calendars.readwrite") }
            return RecoveryPlan(
                kind: .signedOut(.outlook, RecoveryPlan.Lost(mail: true, calendar: hadCalendar && !calendarWritable)),
                actions: [RecoveryAction(signIn: .outlook, verb: .reconnect)]
            )
        }
        if googleMailLost || googleCalendarLost {
            return RecoveryPlan(
                kind: .signedOut(.google, RecoveryPlan.Lost(mail: googleMailLost, calendar: googleCalendarLost)),
                actions: [RecoveryAction(signIn: .google, verb: .reconnect)]
            )
        }

        let gmailActive = gmail?.isActive == true
        let outlookActive = outlook?.isActive == true
        if !gmailActive && !outlookActive {
            // Two equal choices are right here: Selko cannot know which mail the user has.
            return RecoveryPlan(kind: .connectEmail, actions: [
                RecoveryAction(signIn: .google, verb: .connectEmail),
                RecoveryAction(signIn: .outlook, verb: .connectEmail)
            ])
        }
        if !calendarWritable {
            // Offer the calendar of the account the user already signed in with.
            return RecoveryPlan(kind: .connectCalendar, actions: [
                RecoveryAction(signIn: gmailActive ? .google : .outlook, verb: .connectCalendar)
            ])
        }
        return nil
    }
}

/// One sign-in the connection banner can offer.
struct RecoveryAction: Equatable {
    enum SignIn: Equatable { case google, outlook }
    enum Verb: Equatable { case reconnect, connectEmail, connectCalendar }

    let signIn: SignIn
    let verb: Verb

    /// Gmail stands in for the combined Google consent, which grants Gmail
    /// and Google Calendar together (`/integrations/google/auth`).
    var authProvider: IntegrationProvider { signIn == .google ? .gmail : .outlook }

    var label: String {
        switch (verb, signIn) {
        case (.reconnect, .google): "Reconnect Google"
        case (.reconnect, .outlook): "Reconnect Outlook"
        case (.connectEmail, .google): "Connect Gmail"
        case (.connectEmail, .outlook): "Connect Outlook"
        case (.connectCalendar, .google): "Connect Google Calendar"
        case (.connectCalendar, .outlook): "Connect Outlook Calendar"
        }
    }
}

struct RecoveryPlan: Equatable {
    /// What a lapsed sign-in stopped doing.
    struct Lost: Equatable {
        let mail: Bool
        let calendar: Bool
    }

    enum Kind: Equatable {
        case signedOut(RecoveryAction.SignIn, Lost)
        case accounts
        case connectEmail
        case connectCalendar
    }

    let kind: Kind
    let actions: [RecoveryAction]

    var title: String {
        switch kind {
        case .signedOut(.google, _): "Reconnect your Google account"
        case .signedOut(.outlook, _): "Reconnect your Outlook account"
        case .accounts: "Reconnect your accounts"
        case .connectEmail: "Connect your email"
        case .connectCalendar: "Connect a calendar"
        }
    }

    var message: String {
        switch kind {
        case let .signedOut(signIn, lost):
            let mail = signIn == .google ? "Gmail" : "mail"
            let calendar = signIn == .google ? "Google Calendar" : "Outlook Calendar"
            let account = signIn == .google ? "Google" : "Outlook"
            if lost.mail && lost.calendar {
                return "Selko lost access to \(account), so it can’t read new \(mail) or add events to \(calendar). Sign in again to pick up where it left off."
            }
            if lost.mail {
                return "Selko lost access to \(account), so it can’t read new \(mail). Sign in again to pick up where it left off."
            }
            return "Selko lost access to \(calendar). You can keep reviewing suggestions, and accept them once you sign in again."
        case .accounts:
            return "Selko lost access to Google and Outlook, so it can’t read new email or update your calendar."
        case .connectEmail:
            return "Selko finds events in your email. Connect the account you use to get started."
        case .connectCalendar:
            return "Selko needs a calendar to add events to. You can review suggestions now and accept them once a calendar is connected."
        }
    }
}

extension Integration {
    static var mock: Integration {
        Integration(
            id: UUID(),
            userId: UUID(),
            provider: .gmail,
            status: .active,
            providerEmail: "user@gmail.com",
            scopes: ["https://www.googleapis.com/auth/gmail.readonly"],
            lastSyncAt: Date(),
            createdAt: Date(),
            updatedAt: Date()
        )
    }
}
