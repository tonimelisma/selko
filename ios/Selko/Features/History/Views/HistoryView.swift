//
//  HistoryView.swift
//  Selko
//

import SwiftUI

struct HistoryView: View {
    @State private var viewModel = HistoryViewModel()

    var body: some View {
        Group {
            if viewModel.isLoading && viewModel.dateGroups.isEmpty {
                ProgressView("Loading history...")
                    .accessibilityIdentifier("historyLoading")
            } else if viewModel.dateGroups.isEmpty {
                ContentUnavailableView {
                    Label("No Activity", systemImage: "clock")
                } description: {
                    Text("Your reviewed events will appear here.")
                }
                .accessibilityIdentifier("historyEmptyState")
            } else {
                historyList
            }
        }
        .navigationTitle("History")
        .task {
            await viewModel.load()
        }
        .refreshable {
            await viewModel.load()
        }
        .alert("Error", isPresented: .constant(viewModel.errorMessage != nil)) {
            Button("OK") {
                viewModel.errorMessage = nil
            }
        } message: {
            if let error = viewModel.errorMessage {
                Text(error)
            }
        }
    }

    private var historyList: some View {
        List {
            ForEach(viewModel.dateGroups) { group in
                Section(group.label) {
                    ForEach(group.events) { event in
                        HistoryRowView(event: event) {
                            Task { await viewModel.undoEvent(event) }
                        } onRetry: {
                            Task { await viewModel.retrySync(event) }
                        }
                    }
                }
            }

            if viewModel.hasMore {
                Section {
                    Button {
                        Task { await viewModel.loadMore() }
                    } label: {
                        HStack {
                            Spacer()
                            Text("Load More")
                            Spacer()
                        }
                    }
                }
            }
        }
        .listStyle(.insetGrouped)
        .accessibilityIdentifier("historyList")
    }
}

// MARK: - History Row

struct HistoryRowView: View {
    let event: CalendarEvent
    let onUndo: () -> Void
    let onRetry: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                statusIcon
                Text(event.title)
                    .font(.headline)
                    .lineLimit(1)
                Spacer()
                if let updatedAt = event.updatedAt {
                    Text(updatedAt, style: .time)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            Text(statusDescription)
                .font(.subheadline)
                .foregroundStyle(.secondary)

            HStack(spacing: 12) {
                if event.status == .syncFailed {
                    Button("Retry", systemImage: "arrow.clockwise") {
                        onRetry()
                    }
                    .font(.caption)
                    .buttonStyle(.bordered)
                    .controlSize(.mini)
                    .accessibilityIdentifier("retryButton")
                }

                if event.status != .cancelled {
                    Button("Undo", systemImage: "arrow.uturn.backward") {
                        onUndo()
                    }
                    .font(.caption)
                    .buttonStyle(.bordered)
                    .controlSize(.mini)
                    .accessibilityIdentifier("undoButton")
                }
            }
        }
        .padding(.vertical, 4)
    }

    @ViewBuilder
    private var statusIcon: some View {
        switch event.status {
        case .approved:
            Image(systemName: "checkmark.circle.fill")
                .foregroundStyle(.blue)
        case .synced:
            Image(systemName: "checkmark.circle.fill")
                .foregroundStyle(.green)
        case .syncFailed:
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(.orange)
        case .rejected:
            Image(systemName: "xmark.circle.fill")
                .foregroundStyle(.red)
        case .cancelled:
            Image(systemName: "minus.circle.fill")
                .foregroundStyle(.gray)
        default:
            Image(systemName: "circle")
                .foregroundStyle(.secondary)
        }
    }

    private var statusDescription: String {
        switch event.status {
        case .approved:
            return "Approved, waiting to sync"
        case .synced:
            return "Synced to Google Calendar"
        case .syncFailed:
            return "Failed to sync to calendar"
        case .rejected:
            return "Rejected"
        case .cancelled:
            return "Cancelled"
        default:
            return event.status.rawValue
        }
    }
}

#Preview {
    NavigationStack {
        HistoryView()
    }
}
