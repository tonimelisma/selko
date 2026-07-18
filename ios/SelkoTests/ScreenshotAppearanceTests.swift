import SwiftUI
import Testing
@testable import iOS

struct ScreenshotAppearanceTests {
    @Test func parsesExplicitLightAndDarkSchemes() {
        #expect(ScreenshotAppearance.colorScheme(arguments: ["Selko", ScreenshotAppearance.argument, "light"]) == .light)
        #expect(ScreenshotAppearance.colorScheme(arguments: ["Selko", ScreenshotAppearance.argument, "dark"]) == .dark)
    }

    @Test func preservesSystemAppearanceForNormalOrInvalidLaunches() {
        #expect(ScreenshotAppearance.colorScheme(arguments: ["Selko"]) == nil)
        #expect(ScreenshotAppearance.colorScheme(arguments: ["Selko", ScreenshotAppearance.argument, "sepia"]) == nil)
    }
}
