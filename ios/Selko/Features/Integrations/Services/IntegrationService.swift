//
//  IntegrationService.swift
//  Selko
//

import Foundation
import Supabase

protocol IntegrationServiceProtocol: Sendable {
    func fetchIntegrations() async throws -> [Integration]
    func getIntegration(id: UUID) async throws -> Integration
    func getIntegrationByProvider(_ provider: IntegrationProvider) async throws -> Integration?
    func isProviderConnected(_ provider: IntegrationProvider) async -> Bool
    func deleteIntegration(provider: IntegrationProvider) async throws
    func fetchCalendarRecovery() async throws -> IntegrationRecovery?
}

final class IntegrationService: IntegrationServiceProtocol, @unchecked Sendable {
    private let supabase: SupabaseClient

    // Select only safe fields (excluding tokens)
    private let safeColumns = "id, user_id, provider, status, provider_email, scopes, last_sync_at, created_at, updated_at"

    init(supabase: SupabaseClient) {
        self.supabase = supabase
    }

    func fetchIntegrations() async throws -> [Integration] {
        let integrations: [Integration] = try await supabase.from("integrations")
            .select(safeColumns)
            .order("created_at", ascending: false)
            .execute()
            .value

        return integrations
    }

    func getIntegration(id: UUID) async throws -> Integration {
        let integration: Integration = try await supabase.from("integrations")
            .select(safeColumns)
            .eq("id", value: id)
            .single()
            .execute()
            .value

        return integration
    }

    func getIntegrationByProvider(_ provider: IntegrationProvider) async throws -> Integration? {
        let integrations: [Integration] = try await supabase.from("integrations")
            .select(safeColumns)
            .eq("provider", value: provider.rawValue)
            .execute()
            .value

        return integrations.first
    }

    func isProviderConnected(_ provider: IntegrationProvider) async -> Bool {
        do {
            guard let integration = try await getIntegrationByProvider(provider) else {
                return false
            }
            return integration.isActive
        } catch {
            return false
        }
    }

    func deleteIntegration(provider: IntegrationProvider) async throws {
        try await supabase.from("integrations")
            .delete()
            .eq("provider", value: provider.rawValue)
            .execute()
    }

    func fetchCalendarRecovery() async throws -> IntegrationRecovery? {
        let recoveries: [IntegrationRecovery] = try await supabase.from("integration_recoveries")
            .select("id, integration_id, user_id, provider, status, discovered_count, completed_count, remaining_count, error_detail, requested_at")
            .eq("provider", value: IntegrationProvider.googleCalendar.rawValue)
            .order("requested_at", ascending: false)
            .limit(1)
            .execute()
            .value
        return recoveries.first
    }
}
