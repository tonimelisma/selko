//
//  Email.swift
//  Selko
//

import Foundation

struct Email: Identifiable, Codable, Sendable, Equatable {
    let id: UUID
    let userId: UUID
    let integrationId: UUID?
    let gmailId: String
    let threadId: String?
    let subject: String?
    let fromEmail: String?
    let fromName: String?
    let toEmails: [String]?
    let dateSent: Date?
    let snippet: String?
    let gmailLabelIds: [String]
    let isSpam: Bool
    let isTrash: Bool
    let isPromotions: Bool
    let isSocial: Bool
    let isUpdates: Bool
    let isForums: Bool
    let isPrimary: Bool
    let isImportant: Bool
    let isStarred: Bool
    let isUnread: Bool
    let hasAttachments: Bool
    let createdAt: Date?

    enum CodingKeys: String, CodingKey {
        case id
        case userId = "user_id"
        case integrationId = "integration_id"
        case gmailId = "gmail_id"
        case threadId = "thread_id"
        case subject
        case fromEmail = "from_email"
        case fromName = "from_name"
        case toEmails = "to_emails"
        case dateSent = "date_sent"
        case snippet
        case gmailLabelIds = "gmail_label_ids"
        case isSpam = "is_spam"
        case isTrash = "is_trash"
        case isPromotions = "is_promotions"
        case isSocial = "is_social"
        case isUpdates = "is_updates"
        case isForums = "is_forums"
        case isPrimary = "is_primary"
        case isImportant = "is_important"
        case isStarred = "is_starred"
        case isUnread = "is_unread"
        case hasAttachments = "has_attachments"
        case createdAt = "created_at"
    }

    var displaySender: String {
        fromName ?? fromEmail ?? "Unknown"
    }
}

extension Email {
    static var mock: Email {
        Email(
            id: UUID(),
            userId: UUID(),
            integrationId: nil,
            gmailId: "mock-gmail-id",
            threadId: "mock-thread-id",
            subject: "Test Email",
            fromEmail: "sender@example.com",
            fromName: "Test Sender",
            toEmails: ["recipient@example.com"],
            dateSent: Date(),
            snippet: "This is a test email...",
            gmailLabelIds: ["INBOX"],
            isSpam: false,
            isTrash: false,
            isPromotions: false,
            isSocial: false,
            isUpdates: false,
            isForums: false,
            isPrimary: true,
            isImportant: false,
            isStarred: false,
            isUnread: true,
            hasAttachments: false,
            createdAt: Date()
        )
    }
}
