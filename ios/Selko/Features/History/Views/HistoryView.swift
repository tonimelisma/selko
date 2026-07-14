//
//  HistoryView.swift
//  Selko
//

import SwiftUI

struct HistoryView: View {
    let email: String
    @State private var viewModel = HistoryViewModel()

    init(email: String = "") {
        self.email = email
    }

    var body: some View {
        VStack(spacing: 0) {
            SelkoScreenHeader(title: "History", subtitle: "A clear record of what Selko handled for you.", email: email)
            Group {
                if viewModel.isLoading && viewModel.dateGroups.isEmpty {
                    ProgressView("Loading history...")
                        .tint(Color.accentColor)
                        .accessibilityIdentifier("historyLoading")
                } else if viewModel.dateGroups.isEmpty {
                    VStack(spacing: 12) {
                        Image(systemName: "clock")
                            .font(SelkoTypography.sectionTitle)
                            .foregroundStyle(Color.selkoMuted)
                            .frame(width: 60, height: 60)
                            .background(Color.selkoSubtle)
                            .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
                        Text("No activity yet")
                            .font(SelkoTypography.sectionTitle)
                            .foregroundStyle(Color.selkoInk)
                        Text("Your reviewed events will appear here.")
                            .font(SelkoTypography.body)
                            .foregroundStyle(Color.selkoMuted)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .accessibilityIdentifier("historyEmptyState")
                } else {
                    historyList
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .background(Color.selkoPaper.ignoresSafeArea())
        .navigationTitle("History")
        .navigationBarTitleDisplayMode(.inline)
        .task {
            await viewModel.load()
        }
        .refreshable {
            await viewModel.load()
        }
        .alert("Error", isPresented: .constant(viewModel.errorMessage != nil)) {
            if viewModel.canForceUndo {
                Button("Force Undo") {
                    Task { await viewModel.forceUndoPendingEvent() }
                }
            }
            Button("OK", role: .cancel) {
                viewModel.clearError()
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
                Section {
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
                } header: {
                    Text(group.label)
                        .selkoOverline()
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
        .scrollContentBackground(.hidden)
        .background(Color.selkoPaper)
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
                        .font(SelkoTypography.title)
                        .foregroundStyle(Color.selkoInk)
                        .lineLimit(1)
                    Spacer()
                    if let updatedAt = event.updatedAt {
                        Text(updatedAt, style: .time)
                            .font(SelkoTypography.caption)
                            .foregroundStyle(Color.selkoFaint)
                    }
                }
                Text(statusDescription)
                    .font(SelkoTypography.caption)
                    .foregroundStyle(Color.selkoMuted)
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
                .font(SelkoTypography.caption)
                .buttonStyle(.bordered)
                    .tint(Color.selkoWarning)
                .accessibilityIdentifier("retryButton")
            } else if event.status != .cancelled && event.status != .pendingReview {
                Button {
                    onUndo()
                } label: {
                    Label("Undo", systemImage: "arrow.uturn.backward")
                }
                .font(SelkoTypography.caption)
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
                .foregroundStyle(Color.selkoSuccess)
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
                .foregroundStyle(Color.selkoRust)
                .accessibilityLabel("Rejected")
        case .cancelled:
            Image(systemName: "minus.circle.fill")
                .foregroundStyle(Color.selkoMuted)
                .accessibilityLabel("Cancelled")
            default:
                Image(systemName: "circle")
                .foregroundStyle(Color.selkoMuted)
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
