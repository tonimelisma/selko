//
//  MockIntegrationService.swift
//  SelkoTests
//

import Foundation
@testable import iOS

final class MockIntegrationService: IntegrationServiceProtocol, @unchecked Sendable {
    var fetchIntegrationsResult: Result<[Integration], Error> = .success([])

    func fetchIntegrations() async throws -> [Integration] {
        switch fetchIntegrationsResult {
        case .success(let integrations): return integrations
        case .failure(let error): throw error
        }
    }

    func getIntegration(id: UUID) async throws -> Integration {
        return .mock
    }

    func getIntegrationByProvider(_ provider: IntegrationProvider) async throws -> Integration? {
        return nil
    }

    func isProviderConnected(_ provider: IntegrationProvider) async -> Bool {
        return false
    }

    func deleteIntegration(provider: IntegrationProvider) async throws {}
}
