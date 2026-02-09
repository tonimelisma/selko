//
//  BrandColors.swift
//  Selko
//

import SwiftUI

extension Color {
    // MARK: - Primary
    static let selkoPrimary = Color("AccentColor")

    // MARK: - Semantic
    static let selkoSuccess = Color(light: Color(hex: 0x2D8659), dark: Color(hex: 0x3DA873))
    static let selkoError = Color(light: Color(hex: 0xC4384B), dark: Color(hex: 0xE05566))
    static let selkoWarning = Color(light: Color(hex: 0xB8860B), dark: Color(hex: 0xD4A017))

    // MARK: - Helpers
    init(light: Color, dark: Color) {
        self.init(uiColor: UIColor { traits in
            traits.userInterfaceStyle == .dark ? UIColor(dark) : UIColor(light)
        })
    }

    init(hex: UInt, alpha: Double = 1.0) {
        self.init(
            red: Double((hex >> 16) & 0xFF) / 255.0,
            green: Double((hex >> 8) & 0xFF) / 255.0,
            blue: Double(hex & 0xFF) / 255.0,
            opacity: alpha
        )
    }
}
