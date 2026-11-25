import Testing
@testable import iOS

struct SenderGroupViewTests {
    @Test
    func longSenderEmailProducesAValidAvatarPaletteIndex() {
        let email = String(repeating: "long.sender.address.", count: 20) + "@example.com"

        let index = SenderGroupView.avatarPaletteIndex(for: email)

        #expect((0..<3).contains(index))
    }
}
