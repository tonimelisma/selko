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

    /// What the reconnect banner offers: one action per sign-in, not per row.
    /// Gmail and Google Calendar are separate rows but one Google consent
    /// grants both, so offering both only duplicated the same flow. Outlook
    /// mail and Outlook Calendar share one row.
    var recoveryPlan: RecoveryPlan {
        let rows = filter { $0.provider != .googlePhotos }
        let googleRows = rows.filter { $0.provider == .gmail || $0.provider == .googleCalendar }
        let outlook = rows.first { $0.provider == .outlook }
        let emailConnected = rows.contains {
            ($0.provider == .gmail || $0.provider == .outlook) && $0.isActive
        }
        let calendarConnected = rows.hasWritableCalendar

        // A lapsed Gmail always matters. A lapsed Google Calendar matters only
        // when no calendar is writable; with Outlook Calendar working it is not
        // a reason to prompt.
        var wantsGoogle = rows.contains { $0.provider == .gmail && !$0.isActive }
        var wantsOutlook = outlook.map { !$0.isActive } ?? false
        if !emailConnected {
            wantsGoogle = true
            wantsOutlook = true
        } else if !calendarConnected {
            wantsGoogle = true
            if let outlook, !outlook.canWriteCalendar { wantsOutlook = true }
        }

        let google = wantsGoogle
            ? [RecoveryAction(signIn: .google, isReconnect: !googleRows.isEmpty)] : []
        let outlookAction = wantsOutlook
            ? [RecoveryAction(signIn: .outlook, isReconnect: outlook != nil)] : []
        // An Outlook account that only lacks calendar consent is the shortest
        // fix, so it is offered first.
        let outlookFirst = emailConnected && !calendarConnected
            && outlook?.isActive == true && outlook?.canWriteCalendar == false
        let actions = outlookFirst ? outlookAction + google : google + outlookAction

        let title: RecoveryPlan.Title
        if !emailConnected {
            title = .email
        } else if !calendarConnected {
            let hadCalendar = rows.contains { $0.provider == .googleCalendar }
                || (outlook?.scopes.contains { $0.lowercased().hasSuffix("calendars.readwrite") } ?? false)
            title = hadCalendar ? .reconnectCalendar : .connectCalendar
        } else {
            title = .attention
        }
        return RecoveryPlan(title: title, actions: actions)
    }
}

/// One sign-in the reconnect banner can offer.
struct RecoveryAction: Equatable {
    enum SignIn: Equatable { case google, outlook }

    let signIn: SignIn
    let isReconnect: Bool

    /// Gmail stands in for the combined Google consent, which grants Gmail
    /// and Google Calendar together (`/integrations/google/auth`).
    var authProvider: IntegrationProvider { signIn == .google ? .gmail : .outlook }

    var label: String {
        "\(isReconnect ? "Reconnect" : "Connect") \(signIn == .google ? "Google" : "Outlook")"
    }
}

struct RecoveryPlan: Equatable {
    enum Title: Equatable { case email, connectCalendar, reconnectCalendar, attention }

    let title: Title
    let actions: [RecoveryAction]
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
