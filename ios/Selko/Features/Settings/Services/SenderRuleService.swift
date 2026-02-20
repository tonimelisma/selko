//
//  SenderRuleService.swift
//  Selko
//

import Foundation
import Supabase

enum SenderRuleAction: String, Codable, Sendable, CaseIterable {
    case autoApprove = "auto_approve"
    case ignore = "ignore"
}

struct SenderRule: Identifiable, Codable, Sendable {
    let id: UUID
    let userId: UUID
    let senderEmail: String?
    let senderDomain: String?
    let action: String
    let createdAt: Date

    enum CodingKeys: String, CodingKey {
        case id
        case userId = "user_id"
        case senderEmail = "sender_email"
        case senderDomain = "sender_domain"
        case action
        case createdAt = "created_at"
    }

    var ruleAction: SenderRuleAction? {
        SenderRuleAction(rawValue: action)
    }

    /// Display label for the rule's match target (email or domain).
    var displayTarget: String {
        if let email = senderEmail {
            return email
        } else if let domain = senderDomain {
            return "@\(domain)"
        }
        return "Unknown"
    }
}

extension SenderRule {
    static var mock: SenderRule {
        SenderRule(
            id: UUID(),
            userId: UUID(),
            senderEmail: "test@example.com",
            senderDomain: nil,
            action: "ignore",
            createdAt: Date()
        )
    }
}

protocol SenderRuleServiceProtocol: Sendable {
    func fetchRules() async throws -> [SenderRule]
    func createRule(senderEmail: String?, senderDomain: String?, action: SenderRuleAction) async throws -> SenderRule
    func deleteRule(id: UUID) async throws
}

final class SenderRuleService: SenderRuleServiceProtocol, @unchecked Sendable {
    private let supabase: SupabaseClient

    init(supabase: SupabaseClient) {
        self.supabase = supabase
    }

    func fetchRules() async throws -> [SenderRule] {
        let rules: [SenderRule] = try await supabase.from("sender_rules")
            .select()
            .order("created_at", ascending: false)
            .execute()
            .value

        return rules
    }

    func createRule(senderEmail: String?, senderDomain: String?, action: SenderRuleAction) async throws -> SenderRule {
        guard let session = try? await supabase.auth.session else {
            throw BackendAPIError.notAuthenticated
        }

        var insert: [String: AnyJSON] = [
            "user_id": .string(session.user.id.uuidString),
            "action": .string(action.rawValue),
        ]

        if let senderEmail = senderEmail {
            insert["sender_email"] = .string(senderEmail)
        }
        if let senderDomain = senderDomain {
            insert["sender_domain"] = .string(senderDomain)
        }

        let rule: SenderRule = try await supabase.from("sender_rules")
            .insert(insert)
            .select()
            .single()
            .execute()
            .value

        return rule
    }

    func deleteRule(id: UUID) async throws {
        try await supabase.from("sender_rules")
            .delete()
            .eq("id", value: id)
            .execute()
    }
}
