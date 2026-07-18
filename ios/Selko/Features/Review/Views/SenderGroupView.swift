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
                    .clipShape(SelkoShape.navigation)

                VStack(alignment: .leading, spacing: 3) {
                    Text(group.senderName)
                        .font(SelkoTypography.title)
                        .foregroundStyle(Color.selkoInk)
                    if !group.senderEmail.isEmpty && group.senderName != group.senderEmail {
                        Text(group.senderEmail)
                            .font(SelkoTypography.caption)
                            .foregroundStyle(Color.selkoMuted)
                            .lineLimit(1)
                            .truncationMode(.middle)
                    }
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
                        .frame(width: 20, height: 20)
                }
                .buttonStyle(.selko(.secondary))
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
                            Button("Approve all") {
                                withAnimation(.easeInOut(duration: 0.18)) { menuOpen = false }
                                onApproveAll()
                            }
                            .buttonStyle(.selko(.tertiary))
                            .foregroundStyle(Color.selkoSuccessText)
                            Button("Reject all") {
                                withAnimation(.easeInOut(duration: 0.18)) { menuOpen = false }
                                onRejectAll()
                            }
                            .buttonStyle(.selko(.tertiary))
                            .foregroundStyle(Color.selkoError)
                        }
                        .padding(.horizontal, 12)
                        .padding(.vertical, 10)
                        Divider().overlay(Color.selkoDivider)
                    }

                    // One-shot action, not a toggle: creating the rule is
                    // immediate and this view has no rule state to reflect.
                    Button {
                        withAnimation(.easeInOut(duration: 0.18)) { menuOpen = false }
                        onAutoApproveSender()
                    } label: {
                        HStack {
                            Text("Auto-approve sender")
                            Spacer()
                        }
                    }
                    .buttonStyle(.selko(.tertiary))
                    Divider().overlay(Color.selkoDivider)
                    Button {
                        withAnimation(.easeInOut(duration: 0.18)) { menuOpen = false }
                        onIgnoreSender()
                    } label: {
                        HStack {
                            Text("Ignore this sender")
                            Spacer()
                        }
                    }
                    .buttonStyle(.selko(.tertiary))
                    .foregroundStyle(Color.selkoError)
                }
                .background(Color.selkoPaper)
                .clipShape(SelkoShape.control)
                .overlay(SelkoShape.control.stroke(Color.selkoBorder))
                .padding(.horizontal, 14)
                .padding(.bottom, 12)
            }
        }
        .background(Color.selkoSurface)
        .textCase(nil)
    }
}
