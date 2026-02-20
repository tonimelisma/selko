//
//  AppAuthError.swift
//  Selko
//
//  Created by Claude on 1/26/26.
//

import Foundation

enum AppAuthError: Error, LocalizedError, Equatable {
    case invalidCredentials
    case emailAlreadyExists
    case weakPassword
    case networkError
    case serverError(String)
    case unknown(String)

    var errorDescription: String? {
        switch self {
        case .invalidCredentials:
            return String(localized: "Invalid email or password")
        case .emailAlreadyExists:
            return String(localized: "An account with this email already exists")
        case .weakPassword:
            return String(localized: "Password is too weak. Use at least 6 characters")
        case .networkError:
            return String(localized: "Network error. Please check your connection")
        case .serverError(let message):
            return message
        case .unknown(let message):
            return message
        }
    }
}
