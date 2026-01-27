//
//  DependencyContainer.swift
//  Selko
//
//  Created by Claude on 1/26/26.
//

import Foundation
import Supabase

@MainActor
final class DependencyContainer {
    static let shared = DependencyContainer()

    private init() {}

    lazy var supabase: SupabaseClient = {
        SupabaseClient(
            supabaseURL: URL(string: Config.supabaseURL)!,
            supabaseKey: Config.supabaseAnonKey
        )
    }()

    lazy var keychainManager: KeychainManagerProtocol = {
        KeychainManager()
    }()

    lazy var authService: AuthServiceProtocol = {
        AuthService(supabase: supabase)
    }()
}
