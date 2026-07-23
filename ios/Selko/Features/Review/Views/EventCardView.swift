import SwiftUI

struct EventCardView: View {
    let event: CalendarEvent
    var isProcessing: Bool = false
    var onApprove: (() -> Void)? = nil
    var onEdit: (() -> Void)? = nil
    var onReject: (() -> Void)? = nil

    @State private var isDescriptionExpanded = false
    @State private var descriptionOverflows = false
    @State private var truncatedDescriptionHeight: CGFloat = 0
    @State private var fullDescriptionHeight: CGFloat = 0

    private var dateParts: (month: String, day: String) {
        guard let date = event.startDatetime else { return ("", "—") }
        let formatter = DateFormatter()
        formatter.dateFormat = "MMM"
        let month = formatter.string(from: date).uppercased()
        formatter.dateFormat = "d"
        return (month, formatter.string(from: date))
    }

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            VStack(spacing: 2) {
                Text(dateParts.month.isEmpty ? "" : dateParts.month)
                    .font(SelkoTypography.overline)
                    .foregroundStyle(Color.accentColor)
                Text(dateParts.day)
                    .font(SelkoTypography.sectionTitle)
                    .foregroundStyle(Color.selkoInk)
            }
            .frame(width: 50, height: 52)
            .background(Color.selkoSubtle)
            .clipShape(SelkoShape.navigation)

            VStack(alignment: .leading, spacing: 6) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(event.title)
                        .font(SelkoTypography.title)
                        .foregroundStyle(Color.selkoInk)
                        .lineLimit(2)
                        .accessibilityIdentifier("eventTitle")
                    SelkoStateTag(kind: event.status == .pendingChange ? .changed : .new)
                }

                if let startDatetime = event.startDatetime {
                    Text(formattedDateTime(startDatetime, allDay: event.allDay))
                        .font(SelkoTypography.caption)
                        .foregroundStyle(Color.selkoFaint)
                } else if event.allDay {
                    Text("All Day")
                        .font(SelkoTypography.caption)
                        .foregroundStyle(Color.selkoFaint)
                }

                if let location = event.location, !location.isEmpty {
                    Text(location)
                        .font(SelkoTypography.caption)
                        .foregroundStyle(Color.selkoMuted)
                        .lineLimit(1)
                }

                if let description = event.description, !description.isEmpty {
                    descriptionSection(description)
                }

                HStack(spacing: 8) {
                    if isProcessing {
                        ProgressView()
                            .tint(Color.accentColor)
                            .frame(maxWidth: .infinity)
                            .accessibilityIdentifier("eventCardProcessing")
                    } else {
                        if let onApprove {
                            Button(action: onApprove) {
                                Label("Accept", systemImage: "checkmark")
                                    .frame(maxWidth: .infinity)
                            }
                            .buttonStyle(.selko(.success))
                        }
                        if let onEdit {
                            Button(action: onEdit) {
                                Image(systemName: "pencil")
                                    .frame(width: 20, height: 20)
                            }
                            .buttonStyle(.selko(.secondary))
                            .accessibilityLabel("Edit")
                        }
                        if let onReject {
                            Button(role: .destructive, action: onReject) {
                                Image(systemName: "xmark")
                                    .frame(width: 20, height: 20)
                            }
                            .buttonStyle(.selko(.destructiveOutline))
                            .accessibilityLabel("Reject")
                        }
                    }
                }
                .padding(.top, 4)
            }
        }
        .padding(.vertical, 8)
        .accessibilityHint("Double tap to view details")
        .accessibilityIdentifier("eventCard")
        .listRowBackground(Color.clear)
        .onChange(of: event.id) { _, _ in
            resetDescriptionExpansion()
        }
        .onChange(of: event.description) { _, _ in
            resetDescriptionExpansion()
        }
        .onChange(of: truncatedDescriptionHeight) { _, _ in
            updateDescriptionOverflow()
        }
        .onChange(of: fullDescriptionHeight) { _, _ in
            updateDescriptionOverflow()
        }
    }

    @ViewBuilder
    private func descriptionSection(_ description: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(description)
                .font(SelkoTypography.caption)
                .foregroundStyle(Color.selkoMuted)
                .lineLimit(isDescriptionExpanded ? nil : 3)
                .frame(maxWidth: .infinity, alignment: .leading)
                .fixedSize(horizontal: false, vertical: isDescriptionExpanded)
                .background(alignment: .topLeading) {
                    descriptionOverflowProbe(description)
                }

            if descriptionOverflows || isDescriptionExpanded {
                Button {
                    isDescriptionExpanded.toggle()
                } label: {
                    Text(
                        isDescriptionExpanded
                            ? String(localized: "event_card.show_less")
                            : String(localized: "event_card.show_more")
                    )
                    .font(SelkoTypography.caption)
                    .fontWeight(.semibold)
                }
                .buttonStyle(.borderless)
                .foregroundStyle(Color.accentColor)
                .accessibilityAddTraits(.isButton)
                .accessibilityValue(
                    isDescriptionExpanded
                        ? String(localized: "event_card.expanded")
                        : String(localized: "event_card.collapsed")
                )
            }
        }
    }

    private func descriptionOverflowProbe(_ description: String) -> some View {
        ZStack {
            Text(description)
                .font(SelkoTypography.caption)
                .lineLimit(3)
                .fixedSize(horizontal: false, vertical: true)
                .hidden()
                .background(
                    GeometryReader { geometry in
                        Color.clear
                            .preference(
                                key: DescriptionTruncatedHeightKey.self,
                                value: geometry.size.height
                            )
                    }
                )

            Text(description)
                .font(SelkoTypography.caption)
                .fixedSize(horizontal: false, vertical: true)
                .hidden()
                .background(
                    GeometryReader { geometry in
                        Color.clear
                            .preference(
                                key: DescriptionFullHeightKey.self,
                                value: geometry.size.height
                            )
                    }
                )
        }
        .allowsHitTesting(false)
        .accessibilityHidden(true)
        .onPreferenceChange(DescriptionTruncatedHeightKey.self) { height in
            truncatedDescriptionHeight = height
        }
        .onPreferenceChange(DescriptionFullHeightKey.self) { height in
            fullDescriptionHeight = height
        }
    }

    private func updateDescriptionOverflow() {
        guard truncatedDescriptionHeight > 0, fullDescriptionHeight > 0 else { return }
        descriptionOverflows = fullDescriptionHeight > truncatedDescriptionHeight + 1
    }

    private func resetDescriptionExpansion() {
        isDescriptionExpanded = false
        descriptionOverflows = false
        truncatedDescriptionHeight = 0
        fullDescriptionHeight = 0
    }

    private func formattedDateTime(_ date: Date, allDay: Bool) -> String {
        let formatter = DateFormatter()
        if allDay {
            formatter.dateStyle = .medium
            formatter.timeStyle = .none
        } else {
            formatter.dateStyle = .medium
            formatter.timeStyle = .short
        }
        return formatter.string(from: date)
    }
}

private struct DescriptionTruncatedHeightKey: PreferenceKey {
    static var defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = nextValue()
    }
}

private struct DescriptionFullHeightKey: PreferenceKey {
    static var defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = nextValue()
    }
}

#Preview {
    List { EventCardView(event: .mock) }
}
