import Foundation

enum CalendarWorkAction: String, Codable, Sendable { case upsert, cancel }

enum CalendarWorkStatus: String, Codable, Sendable {
    case pending, processing, succeeded, failed, blocked, superseded
}

struct CalendarWorkItem: Identifiable, Codable, Sendable, Equatable {
    let id: UUID
    let eventId: UUID
    let userId: UUID
    let action: CalendarWorkAction
    let generation: Int
    let status: CalendarWorkStatus
    let providerEventId: String?
    let expectedProviderRevision: String?
    let forceOverwrite: Bool
    let attempts: Int
    let maxAttempts: Int
    let nextRetryAt: Date?
    let failureCode: String?
    let failureDetail: String?
    let createdAt: Date?
    let updatedAt: Date?
    let completedAt: Date?

    enum CodingKeys: String, CodingKey {
        case id
        case eventId = "event_id"
        case userId = "user_id"
        case action, generation, status
        case providerEventId = "provider_event_id"
        case expectedProviderRevision = "expected_provider_revision"
        case forceOverwrite = "force_overwrite"
        case attempts
        case maxAttempts = "max_attempts"
        case nextRetryAt = "next_retry_at"
        case failureCode = "failure_code"
        case failureDetail = "failure_detail"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case completedAt = "completed_at"
    }
}
