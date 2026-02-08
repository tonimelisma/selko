//
//  EventCardView.swift
//  Selko
//

import SwiftUI

struct EventCardView: View {
    let event: CalendarEvent

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
        }
        .padding(.vertical, 4)
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
