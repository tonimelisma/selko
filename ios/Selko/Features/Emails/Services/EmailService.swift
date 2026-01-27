//
//  EmailService.swift
//  Selko
//

import Foundation
import Supabase

protocol EmailServiceProtocol: Sendable {
    func fetchEmails(
        limit: Int,
        offset: Int,
        excludeSpam: Bool,
        excludeTrash: Bool,
        excludePromotions: Bool,
        unreadOnly: Bool
    ) async throws -> [Email]
    func getEmail(id: UUID) async throws -> Email
    func updateEmailReadStatus(id: UUID, isUnread: Bool) async throws -> Email
}

extension EmailServiceProtocol {
    func fetchEmails(
        limit: Int = 50,
        offset: Int = 0,
        excludeSpam: Bool = true,
        excludeTrash: Bool = true,
        excludePromotions: Bool = false,
        unreadOnly: Bool = false
    ) async throws -> [Email] {
        try await fetchEmails(
            limit: limit,
            offset: offset,
            excludeSpam: excludeSpam,
            excludeTrash: excludeTrash,
            excludePromotions: excludePromotions,
            unreadOnly: unreadOnly
        )
    }
}

final class EmailService: EmailServiceProtocol, @unchecked Sendable {
    private let supabase: SupabaseClient

    init(supabase: SupabaseClient) {
        self.supabase = supabase
    }

    func fetchEmails(
        limit: Int,
        offset: Int,
        excludeSpam: Bool,
        excludeTrash: Bool,
        excludePromotions: Bool,
        unreadOnly: Bool
    ) async throws -> [Email] {
        var query = supabase.from("emails")
            .select()

        if excludeSpam {
            query = query.eq("is_spam", value: false)
        }
        if excludeTrash {
            query = query.eq("is_trash", value: false)
        }
        if excludePromotions {
            query = query.eq("is_promotions", value: false)
        }
        if unreadOnly {
            query = query.eq("is_unread", value: true)
        }

        let emails: [Email] = try await query
            .order("date_sent", ascending: false)
            .range(from: offset, to: offset + limit - 1)
            .execute()
            .value

        return emails
    }

    func getEmail(id: UUID) async throws -> Email {
        let email: Email = try await supabase.from("emails")
            .select()
            .eq("id", value: id)
            .single()
            .execute()
            .value

        return email
    }

    func updateEmailReadStatus(id: UUID, isUnread: Bool) async throws -> Email {
        let email: Email = try await supabase.from("emails")
            .update(["is_unread": isUnread])
            .eq("id", value: id)
            .select()
            .single()
            .execute()
            .value

        return email
    }
}
