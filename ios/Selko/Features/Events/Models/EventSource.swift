//
//  EventSource.swift
//  Selko
//

import Foundation

enum SourceType: String, Codable, Sendable {
    case newInvitation = "new_invitation"
    case update
    case cancellation
    case reminder
    case unknown
}

enum SourceOrigin: String, Codable, Sendable {
    case email
    case googleCalendar = "google_calendar"
    case googlePhotos = "google_photos"
}

struct ExtractedData: Codable, Sendable, Equatable {
    let title: String?
    let startDatetime: String?
    let endDatetime: String?
    let location: String?
    let description: String?
    let sourceQuote: String?

    enum CodingKeys: String, CodingKey {
        case title
        case startDatetime = "start_datetime"
        case endDatetime = "end_datetime"
        case location
        case description
        case sourceQuote = "source_quote"
    }
}

struct FieldChange: Codable, Sendable, Equatable {
    let field: String
    let before: String?
    let after: String?
    let reason: String?

    enum CodingKeys: String, CodingKey {
        case field, before, after, reason
    }

    init(field: String, before: String?, after: String?, reason: String?) {
        self.field = field
        self.before = before
        self.after = after
        self.reason = reason
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        field = try container.decode(String.self, forKey: .field)
        reason = try container.decodeIfPresent(String.self, forKey: .reason)
        before = Self.decodeFlexibleString(from: container, forKey: .before)
        after = Self.decodeFlexibleString(from: container, forKey: .after)
    }

    private static func decodeFlexibleString(
        from container: KeyedDecodingContainer<CodingKeys>,
        forKey key: CodingKeys
    ) -> String? {
        if let value = try? container.decodeIfPresent(String.self, forKey: key) {
            return value
        }
        if let value = try? container.decodeIfPresent(Bool.self, forKey: key) {
            return value ? "true" : "false"
        }
        if let value = try? container.decodeIfPresent(Double.self, forKey: key) {
            return String(value)
        }
        if let value = try? container.decodeIfPresent(Int.self, forKey: key) {
            return String(value)
        }
        return nil
    }
}

struct EventChangeSet: Codable, Sendable, Equatable {
    let kind: String?
    let changes: [FieldChange]?
    let reasoning: String?
}

struct EventSource: Identifiable, Codable, Sendable, Equatable {
    let id: UUID
    let eventId: UUID
    let emailId: UUID?
    let sourceOrigin: SourceOrigin
    let sourceType: SourceType
    let extractedData: ExtractedData?
    let changeSet: EventChangeSet?
    let isUndone: Bool
    let createdAt: Date?
    let emails: Email?

    enum CodingKeys: String, CodingKey {
        case id
        case eventId = "event_id"
        case emailId = "email_id"
        case sourceOrigin = "source_origin"
        case sourceType = "source_type"
        case extractedData = "extracted_data"
        case changeSet = "change_set"
        case isUndone = "is_undone"
        case createdAt = "created_at"
        case emails
    }
}

extension EventSource {
    static var mock: EventSource {
        EventSource(
            id: UUID(),
            eventId: UUID(),
            emailId: UUID(),
            sourceOrigin: .email,
            sourceType: .newInvitation,
            extractedData: ExtractedData(
                title: "Meeting",
                startDatetime: "2024-01-01T10:00:00Z",
                endDatetime: nil,
                location: "Office",
                description: nil,
                sourceQuote: "Let's meet at..."
            ),
            changeSet: nil,
            isUndone: false,
            createdAt: Date(),
            emails: .mock
        )
    }

    static var mockGooglePhotos: EventSource {
        EventSource(
            id: UUID(),
            eventId: UUID(),
            emailId: nil,
            sourceOrigin: .googlePhotos,
            sourceType: .newInvitation,
            extractedData: ExtractedData(
                title: "Concert",
                startDatetime: "2024-06-15T19:00:00Z",
                endDatetime: nil,
                location: "Arena",
                description: nil,
                sourceQuote: "Event ticket detected in photo"
            ),
            changeSet: nil,
            isUndone: false,
            createdAt: Date(),
            emails: nil
        )
    }
}
