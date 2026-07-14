import SwiftUI

struct SelkoLogoMark: View {
    var size: CGFloat = 40
    var onBrand: Bool = false

    var body: some View {
        Canvas { context, canvasSize in
            let tile = Path(roundedRect: CGRect(origin: .zero, size: canvasSize), cornerRadius: canvasSize.width * 0.3)
            context.fill(tile, with: .color(Color.accentColor))

            let block = onBrand ? Color.selkoPaper : Color.selkoOnPrimary
            let unit = canvasSize.width / 40
            context.fill(Path(roundedRect: CGRect(x: 9 * unit, y: 10 * unit, width: 9 * unit, height: 9 * unit), cornerRadius: 2.5 * unit), with: .color(block))
            context.opacity = 0.55
            context.fill(Path(roundedRect: CGRect(x: 22 * unit, y: 10 * unit, width: 9 * unit, height: 9 * unit), cornerRadius: 2.5 * unit), with: .color(block))
            context.opacity = 0.85
            context.fill(Path(roundedRect: CGRect(x: 9 * unit, y: 23 * unit, width: 22 * unit, height: 8 * unit), cornerRadius: 2.5 * unit), with: .color(block))
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }
}
