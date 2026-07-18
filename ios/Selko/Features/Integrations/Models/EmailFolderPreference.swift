import Foundation

struct EmailFolderPreference: Codable, Identifiable, Equatable, Sendable {
    let id: String
    let provider: String
    let name: String
    let fullPath: String
    let classificationDecision: String
    let classificationReason: String?
    let userOverride: Bool
    let isIncluded: Bool
    let isSystem: Bool

    enum CodingKeys: String, CodingKey {
        case id, provider, name
        case fullPath = "full_path"
        case classificationDecision = "classification_decision"
        case classificationReason = "classification_reason"
        case userOverride = "user_override"
        case isIncluded = "is_included"
        case isSystem = "is_system"
    }

    func withIncluded(_ included: Bool) -> Self {
        Self(
            id: id, provider: provider, name: name, fullPath: fullPath,
            classificationDecision: classificationDecision,
            classificationReason: classificationReason, userOverride: userOverride,
            isIncluded: included, isSystem: isSystem
        )
    }
}
