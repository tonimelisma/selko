//
//  Integration.swift
//  Selko
//

import Foundation

enum IntegrationProvider: String, Codable, Sendable {
    case gmail
    case googlePhotos = "google_photos"
    case googleCalendar = "google_calendar"
}

enum IntegrationStatus: String, Codable, Sendable {
    case active
    case expired
    case revoked
    case error
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
