import Foundation
import Testing
@testable import iOS

struct BackendAPIFolderTests {
    @Test
    func folderPathsRestrictProvidersAndEncodeOpaqueIds() {
        #expect(BackendAPI.emailFolderPath(provider: "gmail") == "/integrations/gmail/folders")
        #expect(
            BackendAPI.emailFolderPath(provider: "outlook", folderId: "A/B+C==")
                == "/integrations/outlook/folders/A%2FB%2BC%3D%3D"
        )
        #expect(BackendAPI.emailFolderPath(provider: "calendar") == nil)
    }

    @Test
    func folderResponseDecodesExistingBackendContract() throws {
        let data = Data("""
        {
          "id": "row-1",
          "provider": "gmail",
          "name": "Promotions",
          "full_path": "[Gmail]/Promotions",
          "classification_decision": "exclude",
          "classification_reason": "Promotional and marketing emails",
          "user_override": false,
          "is_included": false,
          "is_system": false
        }
        """.utf8)

        let folder = try JSONDecoder().decode(EmailFolderPreference.self, from: data)

        #expect(folder.id == "row-1")
        #expect(folder.fullPath == "[Gmail]/Promotions")
        #expect(folder.classificationDecision == "exclude")
        #expect(folder.isIncluded == false)
        #expect(folder.isSystem == false)
    }
}
