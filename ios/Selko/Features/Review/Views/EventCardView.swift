import SwiftUI

struct EventCardView: View {
    let event: CalendarEvent
    var isProcessing: Bool = false
    var onApprove: (() -> Void)? = nil
    var onEdit: (() -> Void)? = nil
    var onReject: (() -> Void)? = nil

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
                    Text(description)
                        .font(SelkoTypography.caption)
                        .foregroundStyle(Color.selkoMuted)
                        .lineLimit(2)
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

#Preview {
    List { EventCardView(event: .mock) }
}
