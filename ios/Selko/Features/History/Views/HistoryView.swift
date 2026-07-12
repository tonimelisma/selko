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
                        HistoryRowView(
                            event: event,
                            isProcessing: viewModel.processingEventIds.contains(event.id)
                        ) {
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
    var isProcessing: Bool = false
    let onUndo: () -> Void
    let onRetry: () -> Void

    var body: some View {
        HStack(alignment: .center) {
            statusIcon
            VStack(alignment: .leading, spacing: 2) {
                HStack {
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
            }

            if isProcessing {
                ProgressView()
                    .controlSize(.small)
                    .accessibilityIdentifier("historyProcessing")
            } else if event.status == .syncFailed {
                Button {
                    onRetry()
                } label: {
                    Label("Retry", systemImage: "arrow.clockwise")
                }
                .font(.caption)
                .buttonStyle(.bordered)
                .tint(.orange)
                .accessibilityIdentifier("retryButton")
            } else if event.status != .cancelled && event.status != .pendingReview {
                Button {
                    onUndo()
                } label: {
                    Label("Undo", systemImage: "arrow.uturn.backward")
                }
                .font(.caption)
                .buttonStyle(.bordered)
                .accessibilityIdentifier("undoButton")
            }
        }
        .padding(.vertical, 4)
    }

    @ViewBuilder
    private var statusIcon: some View {
        switch event.status {
        case .approved:
            Image(systemName: "checkmark.circle.fill")
                .foregroundStyle(Color.accentColor)
                .accessibilityLabel("Approved")
        case .synced:
            Image(systemName: "checkmark.circle.fill")
                .foregroundStyle(Color.selkoSuccess)
                .accessibilityLabel("Synced")
        case .syncFailed:
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(Color.selkoWarning)
                .accessibilityLabel("Sync failed")
        case .rejected:
            Image(systemName: "xmark.circle.fill")
                .foregroundStyle(Color.selkoError)
                .accessibilityLabel("Rejected")
        case .cancelled:
            Image(systemName: "minus.circle.fill")
                .foregroundStyle(.secondary)
                .accessibilityLabel("Cancelled")
        default:
            Image(systemName: "circle")
                .foregroundStyle(.secondary)
                .accessibilityLabel("Pending")
        }
    }

    private var statusDescription: String {
        switch event.status {
        case .approved:
            return String(localized: "Approved, waiting to sync")
        case .synced:
            return String(localized: "Synced to Google Calendar")
        case .syncFailed:
            return String(localized: "Failed to sync to calendar")
        case .rejected:
            return String(localized: "Rejected")
        case .cancelled:
            return String(localized: "Cancelled")
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
