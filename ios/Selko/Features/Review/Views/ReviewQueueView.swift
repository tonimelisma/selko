//
//  ReviewQueueView.swift
//  Selko
//

import SwiftUI

struct ReviewQueueView: View {
    let email: String
    @State private var viewModel = ReviewQueueViewModel()
    @State private var showAcceptAllConfirm = false

    init(email: String = "") {
        self.email = email
    }

    var body: some View {
        VStack(spacing: 0) {
            SelkoScreenHeader(title: "Review", subtitle: "Choose what belongs on your calendar.", email: email)
            Group {
                if viewModel.isLoading {
                    ProgressView("Loading events...")
                        .tint(Color.accentColor)
                        .accessibilityIdentifier("reviewQueueLoading")
                } else if !viewModel.isConnected {
                    IntegrationSetupView(
                        gmailConnected: viewModel.gmailConnected,
                        calendarConnected: viewModel.calendarConnected
                    )
                    .accessibilityIdentifier("integrationSetupView")
                } else if viewModel.newSenderGroups.isEmpty && viewModel.changeSenderGroups.isEmpty {
                    emptyState
                } else {
                    eventList
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .background(Color.selkoPaper.ignoresSafeArea())
        .navigationTitle("Review")
        .navigationBarTitleDisplayMode(.inline)
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
        VStack(spacing: 12) {
            Image(systemName: "checkmark")
                .font(SelkoTypography.sectionTitle.weight(.bold))
                .foregroundStyle(Color.selkoSuccess)
                .frame(width: 60, height: 60)
                .background(Color.selkoSubtle)
                .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
            Text("All caught up")
                .font(SelkoTypography.sectionTitle)
                .foregroundStyle(Color.selkoInk)
            Text("No events need your review right now. New events from your emails will appear here.")
                .font(SelkoTypography.body)
                .foregroundStyle(Color.selkoMuted)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 24)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("emptyStateView")
    }

    private var eventList: some View {
        List {
            if !viewModel.newSenderGroups.isEmpty {
                Section {
                    ForEach(viewModel.newSenderGroups) { group in
                        senderRows(group)
                    }
                } header: {
                    Text("New")
                        .selkoOverline()
                }
            }
            if !viewModel.changeSenderGroups.isEmpty {
                Section {
                    ForEach(viewModel.changeSenderGroups) { group in
                        senderRows(group)
                    }
                } header: {
                    Text("Changes")
                        .selkoOverline()
                }
            }
        }
        .listStyle(.insetGrouped)
        .scrollContentBackground(.hidden)
        .background(Color.selkoPaper)
        .safeAreaInset(edge: .bottom) {
            Button {
                showAcceptAllConfirm = true
            } label: {
                Label("Accept all", systemImage: "checkmark")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .tint(Color.accentColor)
            .controlSize(.large)
            .padding(.horizontal, 16)
            .padding(.vertical, 8)
            .background(Color.selkoPaper.opacity(0.96))
        }
        .confirmationDialog(
            "Accept all pending items?",
            isPresented: $showAcceptAllConfirm,
            titleVisibility: .visible
        ) {
            Button("Accept all") {
                Task { await approveAll() }
            }
            Button("Cancel", role: .cancel) { }
        } message: {
            Text("New events are added to your calendar and changes are applied.")
        }
        .accessibilityIdentifier("eventList")
    }

    private func approveAll() async {
        for group in viewModel.newSenderGroups {
            await viewModel.approveAllInGroup(group)
        }
        for group in viewModel.changeSenderGroups {
            await viewModel.approveAllInGroup(group)
        }
    }

    @ViewBuilder
    private func senderRows(_ group: SenderGroup) -> some View {
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
        ForEach(group.events) { event in
            NavigationLink(value: event.id) {
                EventCardView(
                    event: event,
                    isProcessing: viewModel.processingEventIds.contains(event.id),
                    onApprove: { Task { await viewModel.approveEvent(event) } },
                    onEdit: { /* Navigation handled by NavigationLink */ },
                    onReject: { Task { await viewModel.rejectEvent(event) } }
                )
            }
            .disabled(viewModel.processingEventIds.contains(event.id))
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
    }
}

#Preview {
    NavigationStack {
        ReviewQueueView()
    }
}
