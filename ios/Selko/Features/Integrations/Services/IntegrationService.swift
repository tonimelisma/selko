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
    func deleteIntegrations(providers: [IntegrationProvider]) async throws
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

    /// Deletes every listed provider's row in one request. The Google card
    /// passes both Google providers, which share one token.
    func deleteIntegrations(providers: [IntegrationProvider]) async throws {
        try await supabase.from("integrations")
            .delete()
            .in("provider", values: providers.map(\.rawValue))
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
