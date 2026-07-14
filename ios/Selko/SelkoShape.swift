import SwiftUI

enum SelkoShape {
    static let small = RoundedRectangle(cornerRadius: 8, style: .continuous)
    static let button = RoundedRectangle(cornerRadius: 14, style: .continuous)
    static let card = RoundedRectangle(cornerRadius: 22, style: .continuous)
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
