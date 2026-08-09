import SwiftUI

enum SelkoMetrics {
    static let minimumTarget: CGFloat = 48
    static let inputHeight: CGFloat = 46
    static let horizontalPadding: CGFloat = 16
    static let compactHorizontalPadding: CGFloat = 10
    static let contentGap: CGFloat = 8
    static let iconSize: CGFloat = 20
    static let peerGap: CGFloat = 12
    static let iconCompact: CGFloat = 16
    static let reviewMaxWidth: CGFloat = 720
    static let screenGutter: CGFloat = 16
}

enum SelkoActionRole {
    case primary
    case secondary
    case accept
    case success // legacy alias for accept — keep for selector compat, maps to acceptFill
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
        case .success, .accept: return .selkoActionLabel
        case .destructiveFilled: return .selkoActionLabel
        case .destructiveOutline: return .selkoError
        case .secondary: return .selkoActionLabel
        case .tertiary: return .selkoInk
        }
    }

    private func background(configuration: Configuration) -> Color {
        switch role {
        case .primary: return .accentColor
        case .secondary: return .selkoActionEdit
        case .accept, .success: return .selkoActionAccept
        case .destructiveFilled: return .selkoActionReject
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

enum SelkoPeerActionTier: String { case full, compact, labelOnly }

private struct SelkoPeerActionTierKey: EnvironmentKey { static let defaultValue: SelkoPeerActionTier = .full }
extension EnvironmentValues { var selkoPeerTier: SelkoPeerActionTier { get { self[SelkoPeerActionTierKey.self] } set { self[SelkoPeerActionTierKey.self] = newValue } } }

private struct SelkoPeerActionLayout: Layout {
    // Three-tier ladder per spec: tier 1 >352, tier 2 ≤352, tier 3 ≤296; fallback 1+2 if tier 3 still overflows.
    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        guard !subviews.isEmpty else { return .zero }
        let available = proposal.width ?? .infinity
        // Ideal intrinsic row widths per tier (measure unsized, gap peerGap/8)
        func rowWidth(forTier tier: SelkoPeerActionTier) -> CGFloat {
            let gap: CGFloat = tier == .full ? SelkoMetrics.peerGap : SelkoMetrics.contentGap
            let ideal = subviews.map { $0.sizeThatFits(.unspecified).width }.reduce(0,+) + gap*CGFloat(subviews.count-1)
            return ideal
        }
        let w1 = rowWidth(forTier: .full)
        let w2 = rowWidth(forTier: .compact)
        let w3 = rowWidth(forTier: .labelOnly)
        let intrinsic: CGFloat
        if w1 <= available { intrinsic = w1 }
        else if w2 <= available { intrinsic = w2 }
        else if w3 <= available { intrinsic = w3 }
        else { // 1+2 fallback: Accept full width + Edit/Reject row
            let h1 = subviews.first?.sizeThatFits(ProposedViewSize(width: available, height: nil)).height ?? SelkoMetrics.minimumTarget
            let gap = SelkoMetrics.contentGap
            let bottomCount = max(0, subviews.count - 1)
            let bottomHeight: CGFloat = bottomCount > 0 ? (subviews.dropFirst().map { $0.sizeThatFits(ProposedViewSize(width: (available - gap*CGFloat(bottomCount-1))/CGFloat(bottomCount), height: nil)).height }.max() ?? SelkoMetrics.minimumTarget) : 0
            return CGSize(width: available, height: h1 + (bottomCount>0 ? gap + bottomHeight : 0))
        }
        let h = subviews.map { $0.sizeThatFits(ProposedViewSize(width: intrinsic/CGFloat(subviews.count), height: nil)).height }.max() ?? SelkoMetrics.minimumTarget
        return CGSize(width: min(intrinsic, available), height: h)
    }
    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        guard !subviews.isEmpty else { return }
        let available = bounds.width
        func gap(forTier tier: SelkoPeerActionTier) -> CGFloat { tier == .full ? SelkoMetrics.peerGap : SelkoMetrics.contentGap }
        func idealWidth(forTier tier: SelkoPeerActionTier) -> CGFloat {
            let g = gap(forTier: tier)
            return subviews.map { $0.sizeThatFits(.unspecified).width }.reduce(0,+) + g*CGFloat(subviews.count-1)
        }
        var chosen: SelkoPeerActionTier = .full
        if idealWidth(forTier: .full) > available { chosen = .compact }
        if idealWidth(forTier: chosen) > available && chosen == .compact { chosen = .labelOnly }
        if idealWidth(forTier: .labelOnly) > available {
            // 1+2 fallback
            let g = SelkoMetrics.contentGap
            let top = subviews.first!
            let th = top.sizeThatFits(ProposedViewSize(width: available, height: nil)).height
            top.place(at: CGPoint(x: bounds.minX, y: bounds.minY), anchor: .topLeading, proposal: ProposedViewSize(width: available, height: th))
            let rest = Array(subviews.dropFirst())
            if !rest.isEmpty {
                let bw = (available - g*CGFloat(rest.count-1))/CGFloat(rest.count)
                let y = bounds.minY + th + g
                for (i, sv) in rest.enumerated() {
                    sv.place(at: CGPoint(x: bounds.minX + CGFloat(i)*(bw+g), y: y), anchor: .topLeading, proposal: ProposedViewSize(width: bw, height: nil))
                }
            }
            return
        }
        let g = gap(forTier: chosen)
        let ideal = idealWidth(forTier: chosen)
        let rowW = min(ideal, available)
        let slot = (rowW - g*CGFloat(subviews.count-1))/CGFloat(subviews.count)
        for (i, sv) in subviews.enumerated() {
            sv.place(at: CGPoint(x: bounds.minX + CGFloat(i)*(slot+g), y: bounds.minY), anchor: .topLeading, proposal: ProposedViewSize(width: slot, height: bounds.height))
        }
    }
}

struct SelkoPeerActionGroup<Content: View>: View {
    private let content: () -> Content
    init(@ViewBuilder content: @escaping () -> Content) { self.content = content }
    var body: some View {
        GeometryReader { proxy in
            let w = proxy.size.width
            let tier: SelkoPeerActionTier = w <= 296 ? .labelOnly : (w <= 352 ? .compact : .full)
            SelkoPeerActionLayout { content() }
                .environment(\.selkoPeerTier, tier)
        }
        .frame(height: SelkoMetrics.minimumTarget)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct SelkoActionLabel: View {
    let title: String
    let systemImage: String
    @Environment(\.selkoPeerTier) private var tier
    var body: some View {
        HStack(spacing: (tier == .full ? SelkoMetrics.contentGap : 6)) {
            if tier != .labelOnly {
                Image(systemName: systemImage)
                    .font(.system(size: tier == .compact ? SelkoMetrics.iconCompact : SelkoMetrics.iconSize))
            }
            Text(title).lineLimit(1).fixedSize(horizontal: true, vertical: false)
        }
        .padding(.horizontal, tier == .full ? SelkoMetrics.horizontalPadding : SelkoMetrics.compactHorizontalPadding)
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
