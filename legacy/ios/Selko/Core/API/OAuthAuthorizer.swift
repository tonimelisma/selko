import Foundation
import Observation

@MainActor
@Observable
final class OAuthAuthorizer {
    private let backendAPI: BackendAPIProtocol

    var connectingProvider: IntegrationProvider?
    var errorMessage: String?

    init(backendAPI: BackendAPIProtocol? = nil) {
        self.backendAPI = backendAPI ?? DependencyContainer.shared.backendAPI
    }

    func authorizationURL(for provider: IntegrationProvider) async -> URL? {
        guard connectingProvider == nil, provider != .googlePhotos else { return nil }
        connectingProvider = provider
        errorMessage = nil
        defer { connectingProvider = nil }

        do {
            return try await backendAPI.startOAuth(provider: provider)
        } catch {
            errorMessage = error.localizedDescription
            return nil
        }
    }

    func reportOpenFailure() {
        errorMessage = "Couldn’t open authorization. Please try again."
    }
}
