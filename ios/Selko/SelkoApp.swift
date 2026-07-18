//
//  SelkoApp.swift
//  Selko
//
//  Created by Toni Melisma on 1/26/26.
//

import SwiftUI

enum ScreenshotAppearance {
    static let argument = "--selko-screenshot-appearance"

    static func colorScheme(arguments: [String] = ProcessInfo.processInfo.arguments) -> ColorScheme? {
        guard let index = arguments.firstIndex(of: argument), arguments.indices.contains(index + 1) else {
            return nil
        }

        switch arguments[index + 1].lowercased() {
        case "light": return .light
        case "dark": return .dark
        default: return nil
        }
    }
}

private struct ScreenshotAppearanceProbe: View {
    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        Color.clear
            .frame(width: 1, height: 1)
            .allowsHitTesting(false)
            .accessibilityElement(children: .ignore)
            .accessibilityIdentifier("screenshotAppearanceProbe")
            .accessibilityValue(colorScheme == .dark ? "dark" : "light")
    }
}

@main
struct SelkoApp: App {
    @State private var router = AppRouter()

    var body: some Scene {
        WindowGroup {
            Group {
                if router.isLoading {
                    ProgressView("Loading...")
                        .tint(Color.accentColor)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .background(Color.selkoPaper.ignoresSafeArea())
                } else if router.isAuthenticated {
                    MainTabView(router: router)
                } else {
                    LoginView()
                }
            }
            .onOpenURL { url in
                router.handleDeepLink(url)
            }
            // Screenshot tests opt into an explicit scheme so their baselines
            // cannot inherit stale simulator appearance. Normal launches keep
            // following the user's system setting.
            .preferredColorScheme(ScreenshotAppearance.colorScheme())
            .overlay(alignment: .topLeading) {
                ScreenshotAppearanceProbe()
            }
        }
    }
}
