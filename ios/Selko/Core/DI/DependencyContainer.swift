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
            supabaseURL: {
                guard let url = URL(string: Config.supabaseURL) else {
                    fatalError("Invalid Supabase URL configuration: \(Config.supabaseURL)")
                }
                return url
            }(),
            supabaseKey: Config.supabaseAnonKey
        )
    }()

    lazy var keychainManager: KeychainManagerProtocol = {
        KeychainManager()
    }()

    lazy var authService: AuthServiceProtocol = {
        AuthService(supabase: supabase)
    }()

    lazy var emailService: EmailServiceProtocol = {
        EmailService(supabase: supabase)
    }()

    lazy var eventService: EventServiceProtocol = {
        EventService(supabase: supabase)
    }()

    lazy var integrationService: IntegrationServiceProtocol = {
        IntegrationService(supabase: supabase)
    }()

    lazy var backendAPI: BackendAPIProtocol = {
        BackendAPI(supabase: supabase)
    }()

    lazy var calendarSettingsService: CalendarSettingsServiceProtocol = {
        CalendarSettingsService(supabase: supabase)
    }()

    lazy var senderRuleService: SenderRuleServiceProtocol = {
        SenderRuleService(supabase: supabase)
    }()
}
