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
                            .clipShape(SelkoShape.card)
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
                    .buttonStyle(.selko(.secondary))
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
            VStack(alignment: .leading, spacing: 2) {
                Text(event.title)
                    .font(SelkoTypography.title)
                    .foregroundStyle(Color.selkoInk)
                    .lineLimit(1)
                HStack(spacing: 8) {
                    statusIndicator
                    SelkoStateTag(kind: isChanged ? .changed : .new)
                    if let updatedAt = event.updatedAt {
                        Text(updatedAt, style: .time)
                            .font(SelkoTypography.caption)
                            .foregroundStyle(Color.selkoFaint)
                    }
                }
            }

            if isProcessing {
                ProgressView()
                    .controlSize(.small)
                    .accessibilityIdentifier("historyProcessing")
            } else if event.status == .syncFailed {
                Button {
                    onRetry()
                } label: {
                    Text("Retry")
                }
                .buttonStyle(.selko(.tertiary))
                .foregroundStyle(Color.selkoWarningText)
                .accessibilityIdentifier("retryButton")
            } else if event.status != .cancelled && event.status != .pendingReview {
                Button {
                    onUndo()
                } label: {
                    Text("Undo")
                }
                .buttonStyle(.selko(.tertiary))
                .accessibilityIdentifier("undoButton")
            }
        }
        .padding(.vertical, 4)
    }

    @ViewBuilder
    private var statusIndicator: some View {
        switch event.status {
        case .approved:
            SelkoStatusIndicator(text: "Approved", systemImage: "checkmark.circle", tone: .success)
        case .synced:
            SelkoStatusIndicator(text: "Synced", systemImage: "checkmark.circle", tone: .success)
        case .syncFailed:
            SelkoStatusIndicator(text: "Failed", systemImage: "exclamationmark.circle", tone: .warning)
        case .rejected:
            SelkoStatusIndicator(text: "Rejected", systemImage: "xmark.circle", tone: .error)
        case .cancelled:
            SelkoStatusIndicator(text: "Cancelled", systemImage: "minus.circle", tone: .neutral)
            default:
                SelkoStatusIndicator(text: event.status.rawValue, systemImage: "circle", tone: .neutral)
        }
    }

    private var isChanged: Bool {
        event.eventSources?.contains { $0.sourceType == .update || $0.sourceType == .cancellation } ?? false
    }

}

#Preview {
    NavigationStack {
        HistoryView()
    }
}
