import SwiftUI

enum SelkoShape {
    static let navigationRadius: CGFloat = 12
    static let controlRadius: CGFloat = 14
    static let cardRadius: CGFloat = 20
    static let navigation = RoundedRectangle(cornerRadius: navigationRadius, style: .continuous)
    static let control = RoundedRectangle(cornerRadius: controlRadius, style: .continuous)
    static let button = control
    static let card = RoundedRectangle(cornerRadius: cardRadius, style: .continuous)
    static let chip = Capsule()
}

struct SelkoCardStyle: ViewModifier {
    @Environment(\.colorScheme) private var colorScheme

    func body(content: Content) -> some View {
        content
            .background(Color.selkoSurface)
            .clipShape(SelkoShape.card)
            .overlay {
                if colorScheme == .dark {
                    SelkoShape.card.stroke(Color.selkoBorder, lineWidth: 1)
                }
            }
            .shadow(
                color: colorScheme == .light ? Color.selkoShadow : .clear,
                radius: colorScheme == .light ? 6 : 0,
                y: colorScheme == .light ? 2 : 0
            )
    }
}

extension View {
    func selkoCard() -> some View {
        modifier(SelkoCardStyle())
    }
}
