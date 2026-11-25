import Foundation
import Testing
@testable import iOS

@MainActor
struct OAuthAuthorizerTests {
    @Test
    func startsOAuthThroughAuthenticatedBackendClient() async {
        let backend = MockBackendAPI()
        backend.oauthStartResult = .success(
            URL(string: "https://accounts.example/authorize")!
        )
        let authorizer = OAuthAuthorizer(backendAPI: backend)

        let url = await authorizer.authorizationURL(for: .gmail)

        #expect(url?.absoluteString == "https://accounts.example/authorize")
        #expect(backend.oauthStartCalls == [.gmail])
        #expect(authorizer.errorMessage == nil)
    }

    @Test
    func keepsOAuthStartFailureVisible() async {
        let backend = MockBackendAPI()
        backend.oauthStartResult = .failure(
            BackendAPIError.serverError("Not authenticated")
        )
        let authorizer = OAuthAuthorizer(backendAPI: backend)

        let url = await authorizer.authorizationURL(for: .googleCalendar)

        #expect(url == nil)
        #expect(authorizer.errorMessage == "Not authenticated")
    }
}
