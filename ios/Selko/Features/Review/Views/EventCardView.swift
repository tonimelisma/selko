//
//  EventCardView.swift
//  Selko
//

import SwiftUI

struct EventCardView: View {
    let event: CalendarEvent
    var onApprove: (() -> Void)? = nil
    var onEdit: (() -> Void)? = nil
    var onReject: (() -> Void)? = nil

    @State private var slideOffset: CGFloat = 0
    @State private var slideOpacity: Double = 1.0

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(event.title)
                .font(.headline)
                .lineLimit(2)
                .accessibilityIdentifier("eventTitle")

            if let startDatetime = event.startDatetime {
                HStack(spacing: 4) {
                    Image(systemName: "clock")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text(formattedDateTime(startDatetime, allDay: event.allDay))
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            }

            if let location = event.location, !location.isEmpty {
                HStack(spacing: 4) {
                    Image(systemName: "location")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text(location)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }

            if let description = event.description, !description.isEmpty {
                Text(description)
                    .font(.subheadline)
                    .foregroundStyle(.tertiary)
                    .lineLimit(2)
            }

            // Action buttons at bottom-right
            if onApprove != nil || onEdit != nil || onReject != nil {
                HStack {
                    Spacer()
                    if let onApprove {
                        Button {
                            withAnimation(.easeIn(duration: 0.3)) {
                                slideOffset = 500
                                slideOpacity = 0
                            }
                            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
                                onApprove()
                            }
                        } label: {
                            Image(systemName: "checkmark")
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(.selkoSuccess)
                        .foregroundStyle(.white)
                        .controlSize(.small)
                    }
                    if let onEdit {
                        Button { onEdit() } label: {
                            Label("Edit", systemImage: "pencil")
                        }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.small)
                    }
                    if let onReject {
                        Button(role: .destructive) {
                            withAnimation(.easeIn(duration: 0.3)) {
                                slideOffset = -500
                                slideOpacity = 0
                            }
                            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
                                onReject()
                            }
                        } label: {
                            Image(systemName: "xmark")
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(.selkoError)
                        .foregroundStyle(.white)
                        .controlSize(.small)
                    }
                }
                .padding(.top, 4)
            }
        }
        .offset(x: slideOffset)
        .opacity(slideOpacity)
        .padding(.vertical, 4)
        .accessibilityHint("Double tap to view details")
        .accessibilityIdentifier("eventCard")
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
    List {
        EventCardView(event: .mock)
    }
}
