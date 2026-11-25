//
//  User.swift
//  Selko
//
//  Created by Claude on 1/26/26.
//

import Foundation

struct User: Identifiable, Equatable, Sendable {
    let id: UUID
    let email: String
    let createdAt: Date?

    init(id: UUID, email: String, createdAt: Date? = nil) {
        self.id = id
        self.email = email
        self.createdAt = createdAt
    }
}

extension User {
    static var mock: User {
        User(
            id: UUID(),
            email: "test@example.com",
            createdAt: Date()
        )
    }
}
