//
//  ReviewQueueView.swift
//  Selko
//

import SwiftUI

struct ReviewQueueView: View {
    let email: String
    let onNavigateToEvent: (UUID) -> Void
    @State private var viewModel = ReviewQueueViewModel(liveUpdateService: DependencyContainer.shared.liveUpdateService)
    @State private var showAcceptAllConfirm = false

    init(email: String = "", onNavigateToEvent: @escaping (UUID) -> Void = { _ in }) {
        self.email = email
        self.onNavigateToEvent = onNavigateToEvent
    }

    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        ZStack(alignment: .bottom) {
            VStack(spacing: 0) {
                SelkoScreenHeader(title: "Review", subtitle: "Choose what belongs on your calendar.", email: email)
                Group {
                    if viewModel.isLoading {
                        ProgressView("Loading events...")
                            .tint(Color.accentColor)
                            .accessibilityIdentifier("reviewQueueLoading")
                    } else if viewModel.isFirstRun {
                        IntegrationSetupView(
                            gmailConnected: false,
                            calendarConnected: false
                        )
                        .accessibilityIdentifier("integrationSetupView")
                    } else if viewModel.newSenderGroups.isEmpty && viewModel.changeSenderGroups.isEmpty {
                        ScrollView {
                            VStack(spacing: 24) {
                                ConnectionRecoveryView(integrations: viewModel.integrations)
                                emptyState
                                    .frame(minHeight: 320)
                            }
                            .padding(SelkoMetrics.screenGutter)
                        }
                    } else {
                        eventList
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .frame(maxWidth: SelkoMetrics.reviewMaxWidth)
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            if viewModel.showUndoToast {
                HStack(spacing: 12) {
                    Text(viewModel.undoToastMessage)
                        .font(SelkoTypography.body)
                        .foregroundStyle(Color.selkoInk)
                        .lineLimit(2)
                        .accessibilityIdentifier("rejectUndoMessage")
                    Spacer()
                    Button("Undo") {
                        Task { await viewModel.undoLastRejected() }
                    }
                    .font(SelkoTypography.title)
                    .foregroundStyle(Color.accentColor)
                    .accessibilityIdentifier("rejectUndoButton")
                    Button("Dismiss") {
                        viewModel.dismissUndoToast()
                    }
                    .font(SelkoTypography.caption)
                    .foregroundStyle(Color.selkoMuted)
                    .accessibilityIdentifier("rejectUndoDismissButton")
                    .accessibilityLabel("Dismiss")
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
                .background(Color.selkoSurface)
                .clipShape(SelkoShape.card)
                .overlay(SelkoShape.card.stroke(Color.selkoBorder, lineWidth: 1))
                .shadow(color: Color.selkoShadow.opacity(0.15), radius: 8, y: 4)
                .padding(.horizontal, SelkoMetrics.screenGutter)
                .padding(.bottom, 12)
                .accessibilityIdentifier("rejectUndoToast")
                .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.selkoPaper.ignoresSafeArea())
        .navigationTitle("Review")
        .navigationBarTitleDisplayMode(.inline)
        .task {
            await viewModel.load()
            viewModel.startLiveUpdates()
        }
        .refreshable {
            await viewModel.load()
        }
        .onDisappear {
            viewModel.stopLiveUpdates()
        }
        .onChange(of: scenePhase) { _, newPhase in
            if newPhase == .active {
                Task { await viewModel.handleScenePhaseActive() }
            }
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
                .clipShape(SelkoShape.card)
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
            if viewModel.hasConnectionIssue {
                ConnectionRecoveryView(integrations: viewModel.integrations)
                    .listRowInsets(EdgeInsets(top: 8, leading: 16, bottom: 8, trailing: 16))
                    .listRowBackground(Color.clear)
            }

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
            .buttonStyle(.selko(.primary))
            .disabled(!viewModel.calendarConnected)
            .accessibilityHint(
                viewModel.calendarConnected
                    ? ""
                    : "Reconnect Google Calendar to accept suggestions."
            )
            .padding(.horizontal, SelkoMetrics.screenGutter)
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
        .frame(maxWidth: SelkoMetrics.reviewMaxWidth)
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
            },
            canApprove: viewModel.calendarConnected
        )
        ForEach(group.events) { event in
            EventCardView(
                event: event,
                isProcessing: viewModel.processingEventIds.contains(event.id),
                canApprove: viewModel.calendarConnected,
                onApprove: { Task { await viewModel.approveEvent(event) } },
                onEdit: { onNavigateToEvent(event.id) },
                onReject: { Task { await viewModel.rejectEvent(event) } }
            )
            .swipeActions(edge: .leading, allowsFullSwipe: true) {
                if viewModel.calendarConnected {
                    Button {
                        Task { await viewModel.approveEvent(event) }
                    } label: {
                        Label("Accept", systemImage: "checkmark")
                    }
                    .tint(.selkoSuccess)
                    .accessibilityLabel("Accept \(event.title)")
                }
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
