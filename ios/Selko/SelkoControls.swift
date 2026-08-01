import SwiftUI

enum SelkoMetrics {
    static let minimumTarget: CGFloat = 48
    static let inputHeight: CGFloat = 46
    static let horizontalPadding: CGFloat = 16
    static let compactHorizontalPadding: CGFloat = 10
    static let contentGap: CGFloat = 8
    static let iconSize: CGFloat = 20
    static let reviewMaxWidth: CGFloat = 720
    static let screenGutter: CGFloat = 16
}

enum SelkoActionRole {
    case primary
    case secondary
    case success
    case destructiveFilled
    case destructiveOutline
    case tertiary
}

struct SelkoButtonStyle: ButtonStyle {
    let role: SelkoActionRole
    @Environment(\.isEnabled) private var isEnabled
    @Environment(\.colorScheme) private var colorScheme

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(SelkoTypography.caption.weight(.bold))
            .frame(minHeight: SelkoMetrics.minimumTarget)
            .padding(.horizontal, SelkoMetrics.horizontalPadding)
            .foregroundStyle(foreground)
            .background(background(configuration: configuration))
            .clipShape(SelkoShape.control)
            .overlay {
                if role == .destructiveOutline {
                    SelkoShape.control.stroke(Color.selkoError, lineWidth: 1.5)
                }
            }
            .shadow(
                color: shadowColor,
                radius: role == .primary && isEnabled ? 8 : 0,
                y: role == .primary && isEnabled ? 4 : 0
            )
            .opacity(isEnabled ? (configuration.isPressed ? 0.78 : 1) : 0.45)
            .contentShape(SelkoShape.control)
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
    }

    private var foreground: Color {
        switch role {
        case .primary: return .selkoOnPrimary
        case .success: return .selkoOnSuccess
        case .destructiveFilled: return .selkoOnError
        case .destructiveOutline: return .selkoError
        case .secondary, .tertiary: return .selkoInk
        }
    }

    private func background(configuration: Configuration) -> Color {
        switch role {
        case .primary: return .accentColor
        case .secondary: return .selkoSubtle
        case .success: return .selkoSuccess
        case .destructiveFilled: return .selkoError
        case .destructiveOutline: return .clear
        case .tertiary: return configuration.isPressed ? .selkoSubtle : .clear
        }
    }

    private var shadowColor: Color {
        guard colorScheme == .light else { return .clear }
        return Color.accentColor.opacity(0.30)
    }
}

extension ButtonStyle where Self == SelkoButtonStyle {
    static func selko(_ role: SelkoActionRole) -> SelkoButtonStyle {
        SelkoButtonStyle(role: role)
    }
}

private struct SelkoPeerActionLayout: Layout {
    func sizeThatFits(
        proposal: ProposedViewSize,
        subviews: Subviews,
        cache: inout ()
    ) -> CGSize {
        guard !subviews.isEmpty else { return .zero }

        let idealWidths = subviews.map { $0.sizeThatFits(.unspecified).width }
        let rowWidth = idealWidths.reduce(0, +) + SelkoMetrics.contentGap * CGFloat(subviews.count - 1)
        let availableWidth = proposal.width ?? rowWidth

        if rowWidth <= availableWidth {
            let itemWidth = (availableWidth - SelkoMetrics.contentGap * CGFloat(subviews.count - 1)) / CGFloat(subviews.count)
            let height = subviews.map {
                $0.sizeThatFits(ProposedViewSize(width: itemWidth, height: nil)).height
            }.max() ?? SelkoMetrics.minimumTarget
            return CGSize(width: availableWidth, height: height)
        }

        let heights = subviews.map {
            $0.sizeThatFits(ProposedViewSize(width: availableWidth, height: nil)).height
        }
        return CGSize(
            width: availableWidth,
            height: heights.reduce(0, +) + SelkoMetrics.contentGap * CGFloat(subviews.count - 1)
        )
    }

    func placeSubviews(
        in bounds: CGRect,
        proposal: ProposedViewSize,
        subviews: Subviews,
        cache: inout ()
    ) {
        guard !subviews.isEmpty else { return }

        let idealWidths = subviews.map { $0.sizeThatFits(.unspecified).width }
        let rowWidth = idealWidths.reduce(0, +) + SelkoMetrics.contentGap * CGFloat(subviews.count - 1)
        let shouldStack = rowWidth > bounds.width

        if !shouldStack {
            let itemWidth = (bounds.width - SelkoMetrics.contentGap * CGFloat(subviews.count - 1)) / CGFloat(subviews.count)
            for (index, subview) in subviews.enumerated() {
                subview.place(
                    at: CGPoint(
                        x: bounds.minX + CGFloat(index) * (itemWidth + SelkoMetrics.contentGap),
                        y: bounds.minY
                    ),
                    anchor: .topLeading,
                    proposal: ProposedViewSize(width: itemWidth, height: bounds.height)
                )
            }
            return
        }

        var y = bounds.minY
        for subview in subviews {
            let height = subview.sizeThatFits(ProposedViewSize(width: bounds.width, height: nil)).height
            subview.place(
                at: CGPoint(x: bounds.minX, y: y),
                anchor: .topLeading,
                proposal: ProposedViewSize(width: bounds.width, height: height)
            )
            y += height + SelkoMetrics.contentGap
        }
    }
}

struct SelkoPeerActionGroup<Content: View>: View {
    private let content: () -> Content

    init(@ViewBuilder content: @escaping () -> Content) {
        self.content = content
    }

    var body: some View {
        SelkoPeerActionLayout {
            content()
        }
        .frame(maxWidth: .infinity)
    }
}

struct SelkoActionLabel: View {
    let title: String
    let systemImage: String

    var body: some View {
        HStack(spacing: SelkoMetrics.contentGap - 2) {
            Image(systemName: systemImage)
            Text(title)
                .lineLimit(1)
                .fixedSize(horizontal: true, vertical: false)
        }
    }
}

struct SelkoInputStyle: ViewModifier {
    func body(content: Content) -> some View {
        content
            .padding(.horizontal, SelkoMetrics.horizontalPadding)
            .frame(minHeight: SelkoMetrics.inputHeight)
            .background(Color.selkoSurface)
            .clipShape(SelkoShape.control)
            .overlay(SelkoShape.control.stroke(Color.selkoBorder, lineWidth: 1))
    }
}

extension View {
    func selkoInput() -> some View { modifier(SelkoInputStyle()) }
}

enum SelkoStatusTone {
    case success, warning, error, neutral
}

struct SelkoStatusIndicator: View {
    let text: String
    let systemImage: String
    let tone: SelkoStatusTone

    var body: some View {
        Label(text, systemImage: systemImage)
            .font(SelkoTypography.caption.weight(.semibold))
            .foregroundStyle(color)
            .accessibilityElement(children: .combine)
    }

    private var color: Color {
        switch tone {
        case .success: return .selkoSuccessText
        case .warning: return .selkoWarningText
        case .error: return .selkoError
        case .neutral: return .selkoMuted
        }
    }
}

enum SelkoStateTagKind { case new, changed }

struct SelkoStateTag: View {
    let kind: SelkoStateTagKind

    var body: some View {
        Text(kind == .new ? "NEW" : "CHANGED")
            .font(SelkoTypography.overline)
            .foregroundStyle(kind == .new ? Color.selkoBadgeNewFg : Color.selkoBadgeChangedFg)
            .padding(.horizontal, 8)
            .frame(height: 20)
            .background(kind == .new ? Color.selkoBadgeNewBg : Color.selkoBadgeChangedBg)
            .clipShape(Capsule())
    }
}
