//
//  ReviewQueueView.swift
//  Selko
//

import SwiftUI

struct ReviewQueueView: View {
    @State private var viewModel = ReviewQueueViewModel()

    var body: some View {
        Group {
            if viewModel.isLoading {
                ProgressView("Loading events...")
                    .accessibilityIdentifier("reviewQueueLoading")
            } else if !viewModel.isConnected {
                IntegrationSetupView(
                    gmailConnected: viewModel.gmailConnected,
                    calendarConnected: viewModel.calendarConnected
                )
                .accessibilityIdentifier("integrationSetupView")
            } else if viewModel.senderGroups.isEmpty {
                emptyState
            } else {
                eventList
            }
        }
        .navigationTitle("Review")
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

    private var emptyState: some View {
        ContentUnavailableView {
            Label("All Caught Up!", systemImage: "checkmark.circle.fill")
        } description: {
            Text("No events need your review right now. New events from your emails will appear here.")
        }
        .accessibilityIdentifier("emptyStateView")
    }

    private var eventList: some View {
        List {
            ForEach(viewModel.senderGroups) { group in
                Section {
                    ForEach(group.events) { event in
                        NavigationLink(value: event.id) {
                            EventCardView(
                                event: event,
                                onApprove: { Task { await viewModel.approveEvent(event) } },
                                onEdit: { /* Navigation handled by NavigationLink */ },
                                onReject: { Task { await viewModel.rejectEvent(event) } }
                            )
                        }
                        .swipeActions(edge: .leading, allowsFullSwipe: true) {
                            Button {
                                Task { await viewModel.approveEvent(event) }
                            } label: {
                                Label("Approve", systemImage: "checkmark")
                            }
                            .tint(.selkoSuccess)
                            .accessibilityLabel("Approve event")
                        }
                        .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                            Button(role: .destructive) {
                                Task { await viewModel.rejectEvent(event) }
                            } label: {
                                Label("Reject", systemImage: "xmark")
                            }
                            .accessibilityLabel("Reject event")
                        }
                    }
                } header: {
                    SenderGroupView(group: group,
                        onApproveAll: {
                            Task { await viewModel.approveAllInGroup(group) }
                        },
                        onRejectAll: {
                            Task { await viewModel.rejectAllInGroup(group) }
                        },
                        onIgnoreSender: {
                            Task { await viewModel.ignoreSender(group) }
                        },
                        onAutoApproveSender: {
                            Task { await viewModel.autoApproveSender(group) }
                        }
                    )
                }
            }
        }
        .listStyle(.insetGrouped)
        .accessibilityIdentifier("eventList")
        .navigationDestination(for: UUID.self) { eventId in
            EventDetailView(eventId: eventId)
        }
    }
}

#Preview {
    NavigationStack {
        ReviewQueueView()
    }
}
