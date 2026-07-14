import SwiftUI

struct SenderGroupView: View {
    let group: SenderGroup
    let onApproveAll: () -> Void
    let onRejectAll: () -> Void
    let onIgnoreSender: () -> Void
    let onAutoApproveSender: () -> Void

    @State private var menuOpen = false

    private var initials: String {
        let source = group.senderName.isEmpty ? group.senderEmail : group.senderName
        return String(source.filter(\.isLetter).prefix(2)).uppercased()
    }

    private var avatarColor: Color {
        let palette: [Color] = [.accentColor, .selkoWarning, .selkoSuccess]
        return palette[Self.avatarPaletteIndex(for: group.senderEmail)]
    }

    static func avatarPaletteIndex(for senderEmail: String) -> Int {
        let hash = senderEmail.unicodeScalars.reduce(UInt64(7)) { hash, scalar in
            hash &* 31 &+ UInt64(scalar.value)
        }
        return Int(hash % 3)
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                Text(initials.isEmpty ? "SK" : initials)
                    .font(SelkoTypography.caption.weight(.bold))
                    .foregroundStyle(Color.selkoOnPrimary)
                    .frame(width: 44, height: 44)
                    .background(avatarColor)
                    .clipShape(RoundedRectangle(cornerRadius: 13, style: .continuous))

                VStack(alignment: .leading, spacing: 3) {
                    Text(group.senderName)
                        .font(SelkoTypography.title)
                        .foregroundStyle(Color.selkoInk)
                    Text("\(group.events.count) \(group.events.count == 1 ? "event" : "events")")
                        .font(SelkoTypography.caption)
                        .foregroundStyle(Color.selkoFaint)
                }
                Spacer()
                Button {
                    withAnimation(.easeInOut(duration: 0.18)) { menuOpen.toggle() }
                } label: {
                    Image(systemName: menuOpen ? "chevron.up" : "chevron.down")
                        .font(SelkoTypography.caption.weight(.bold))
                        .foregroundStyle(Color.selkoInk)
                        .frame(width: 34, height: 34)
                        .background(Color.selkoSubtle)
                        .clipShape(RoundedRectangle(cornerRadius: 11, style: .continuous))
                }
                .accessibilityLabel("Actions for this sender")
                .accessibilityValue(menuOpen ? "Expanded" : "Collapsed")
            }
            .padding(14)

            if menuOpen {
                VStack(spacing: 0) {
                    if group.events.count > 1 {
                        HStack {
                            Text("Bulk actions")
                                .font(SelkoTypography.caption)
                                .foregroundStyle(Color.selkoMuted)
                            Spacer()
                            Button("Approve all", action: onApproveAll)
                                .font(SelkoTypography.caption.weight(.bold))
                                .foregroundStyle(Color.selkoSuccess)
                            Button("Reject all", action: onRejectAll)
                                .font(SelkoTypography.caption.weight(.bold))
                                .foregroundStyle(Color.selkoRust)
                        }
                        .padding(.horizontal, 12)
                        .padding(.vertical, 10)
                        Divider().overlay(Color.selkoDivider)
                    }

                    HStack {
                        Text("Auto-accept events")
                            .font(SelkoTypography.caption.weight(.bold))
                            .foregroundStyle(Color.selkoInk)
                        Spacer()
                        Toggle("Auto-accept events", isOn: Binding(get: { false }, set: { _ in onAutoApproveSender() }))
                            .labelsHidden()
                            .tint(Color.accentColor)
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 10)
                    Divider().overlay(Color.selkoDivider)
                    Button(role: .destructive, action: onIgnoreSender) {
                        HStack {
                            Text("Ignore this sender")
                            Spacer()
                        }
                    }
                    .font(SelkoTypography.caption.weight(.bold))
                    .padding(.horizontal, 12)
                    .padding(.vertical, 10)
                }
                .background(Color.selkoPaper)
                .clipShape(RoundedRectangle(cornerRadius: 15, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 15, style: .continuous).stroke(Color.selkoRust.opacity(0.22)))
                .padding(.horizontal, 14)
                .padding(.bottom, 12)
            }
        }
        .background(Color.selkoSurface)
        .textCase(nil)
    }
}
