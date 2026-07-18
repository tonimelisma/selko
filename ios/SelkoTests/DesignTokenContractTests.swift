import Foundation
import Testing
@testable import iOS

struct DesignTokenContractTests {
    private var repositoryRoot: URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
    }

    private func manifest() throws -> [String: Any] {
        let data = try Data(contentsOf: repositoryRoot.appending(path: "design/tokens.json"))
        return try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    @Test
    func geometryMatchesCanonicalManifest() throws {
        let root = try manifest()
        let shape = try #require(root["shape"] as? [String: NSNumber])
        let control = try #require(root["control"] as? [String: NSNumber])

        #expect(SelkoShape.navigationRadius == CGFloat(truncating: shape["navigation"]!))
        #expect(SelkoShape.controlRadius == CGFloat(truncating: shape["control"]!))
        #expect(SelkoShape.cardRadius == CGFloat(truncating: shape["card"]!))
        #expect(SelkoMetrics.minimumTarget == CGFloat(truncating: control["minimumTarget"]!))
        #expect(SelkoMetrics.inputHeight == CGFloat(truncating: control["inputHeight"]!))
        #expect(SelkoMetrics.horizontalPadding == CGFloat(truncating: control["horizontalPadding"]!))
        #expect(SelkoMetrics.contentGap == CGFloat(truncating: control["contentGap"]!))
        #expect(SelkoMetrics.iconSize == CGFloat(truncating: control["icon"]!))
    }

    @Test
    func semanticAssetColorsMatchCanonicalManifest() throws {
        let root = try manifest()
        let colors = try #require(root["color"] as? [String: [String: String]])
        let mappings = [
            ("AccentColor", "primary"),
            ("SelkoOnPrimary", "onPrimary"),
            ("SelkoSuccess", "success"),
            ("SelkoOnSuccess", "onSuccess"),
            ("SelkoSuccessText", "successText"),
            ("SelkoWarning", "warning"),
            ("SelkoWarningText", "warningText"),
            ("SelkoError", "error"),
            ("SelkoMuted", "muted"),
            ("SelkoFaint", "faint"),
            ("SelkoBadgeNewBg", "newBackground"),
            ("SelkoBadgeNewFg", "newForeground"),
            ("SelkoBadgeChangedBg", "changedBackground"),
            ("SelkoBadgeChangedFg", "changedForeground")
        ]

        for (asset, token) in mappings {
            let light = try #require(colors["light"]?[token])
            let dark = try #require(colors["dark"]?[token])
            let values = try assetHexValues(named: asset)
            #expect(values.light == light.uppercased(), "\(asset) light drifted")
            #expect(values.dark == dark.uppercased(), "\(asset) dark drifted")
        }
    }

    private func assetHexValues(named name: String) throws -> (light: String, dark: String) {
        let url = repositoryRoot.appending(path: "ios/Selko/Assets.xcassets/\(name).colorset/Contents.json")
        let data = try Data(contentsOf: url)
        let json = try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
        let colors = try #require(json["colors"] as? [[String: Any]])
        return try (hex(colors[0]), hex(colors[1]))
    }

    private func hex(_ item: [String: Any]) throws -> String {
        let color = try #require(item["color"] as? [String: Any])
        let components = try #require(color["components"] as? [String: String])
        let red = Int(round((Double(components["red"]!) ?? 0) * 255))
        let green = Int(round((Double(components["green"]!) ?? 0) * 255))
        let blue = Int(round((Double(components["blue"]!) ?? 0) * 255))
        return String(format: "#%02X%02X%02X", red, green, blue)
    }
}
