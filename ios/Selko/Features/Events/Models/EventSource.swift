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

struct EventSource: Identifiable, Codable, Sendable, Equatable {
    let id: UUID
    let eventId: UUID
    let emailId: UUID?
    let sourceOrigin: SourceOrigin
    let sourceType: SourceType
    let extractedData: ExtractedData?
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
            isUndone: false,
            createdAt: Date(),
            emails: nil
        )
    }
}
