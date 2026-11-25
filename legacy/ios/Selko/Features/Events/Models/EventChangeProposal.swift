import Foundation

enum EventChangeProposalKind: String, Codable, Sendable {
    case materialUpdate = "material_update"
    case cancellation
}

enum EventChangeProposalStatus: String, Codable, Sendable {
    case pending
    case applied
    case rejected
    case superseded
    case closedLegacy = "closed_legacy"
}

struct EventChangeProposal: Identifiable, Codable, Sendable, Equatable {
    let id: UUID
    let eventId: UUID
    let userId: UUID
    let sourceId: UUID
    let kind: EventChangeProposalKind
    let status: EventChangeProposalStatus
    let changeSet: EventChangeSet
    let resolutionReason: String?
    let createdAt: Date?
    let resolvedAt: Date?
    let updatedAt: Date?

    enum CodingKeys: String, CodingKey {
        case id
        case eventId = "event_id"
        case userId = "user_id"
        case sourceId = "source_id"
        case kind, status
        case changeSet = "change_set"
        case resolutionReason = "resolution_reason"
        case createdAt = "created_at"
        case resolvedAt = "resolved_at"
        case updatedAt = "updated_at"
    }
}
