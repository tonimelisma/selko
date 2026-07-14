import SwiftUI

enum SelkoTypography {
    static let display = Font.custom("Figtree-ExtraBold", size: 40, relativeTo: .largeTitle)
        .weight(.heavy)
    static let screenTitle = Font.custom("Figtree-ExtraBold", size: 26, relativeTo: .largeTitle)
    static let pageTitle = Font.custom("Figtree-ExtraBold", size: 30, relativeTo: .largeTitle)
    static let sectionTitle = Font.custom("Figtree-Bold", size: 23, relativeTo: .title2)
    static let title = Font.custom("Figtree-Bold", size: 15, relativeTo: .body)
    static let body = Font.custom("Figtree-Regular", size: 15, relativeTo: .body)
    static let caption = Font.custom("Figtree-Medium", size: 12, relativeTo: .caption)
    static let overline = Font.custom("Figtree-Bold", size: 11, relativeTo: .caption)
}

struct SelkoOverline: ViewModifier {
    @Environment(\.colorScheme) private var colorScheme

    func body(content: Content) -> some View {
        content
            .font(SelkoTypography.overline)
            .textCase(.uppercase)
            .kerning(0.9)
            .foregroundStyle(colorScheme == .dark ? Color.accentColor : Color.selkoRust)
    }
}

extension View {
    func selkoOverline() -> some View {
        modifier(SelkoOverline())
    }
}
