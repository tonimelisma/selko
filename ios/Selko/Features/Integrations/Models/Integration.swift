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
