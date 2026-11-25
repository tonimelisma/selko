//
//  AuthState.swift
//  Selko
//
//  Created by Claude on 1/26/26.
//

import Foundation

enum AuthState: Equatable, Sendable {
    case unknown
    case authenticated(User)
    case unauthenticated
}
