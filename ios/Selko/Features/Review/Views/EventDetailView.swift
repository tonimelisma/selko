//
//  EventDetailView.swift
//  Selko
//

import SwiftUI

struct EventDetailView: View {
    @State private var viewModel: EventDetailViewModel
    @Environment(\.dismiss) private var dismiss
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass

    init(eventId: UUID) {
        _viewModel = State(initialValue: EventDetailViewModel(eventId: eventId))
    }

    var body: some View {
        Group {
            if viewModel.isLoading {
                ProgressView("Loading event...")
            } else if let _ = viewModel.event {
                if horizontalSizeClass == .regular {
                    // iPad: side-by-side layout
                    HStack(alignment: .top, spacing: 0) {
                        sourcePanel
                            .frame(maxWidth: .infinity)
                        Divider()
                        formPanel
                            .frame(maxWidth: .infinity)
                    }
                } else {
                    // iPhone: stacked layout
                    ScrollView {
                        VStack(spacing: 0) {
                            formPanel
                            sourceDisclosure
                        }
                    }
                }
            } else if let error = viewModel.errorMessage {
                ContentUnavailableView {
                    Label("Error", systemImage: "exclamationmark.triangle")
                } description: {
                    Text(error)
                }
            }
        }
        .navigationTitle("Event Detail")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button(role: .destructive) {
                    Task {
                        await viewModel.reject()
                    }
                } label: {
                    Text("Reject")
                        .foregroundStyle(.red)
                        .accessibilityIdentifier("rejectButton")
                }
            }

            ToolbarItem(placement: .confirmationAction) {
                Button {
                    Task {
                        await viewModel.approve()
                    }
                } label: {
                    Text("Approve")
                        .fontWeight(.semibold)
                        .accessibilityIdentifier("approveButton")
                }
                .tint(.green)
            }
        }
        .task {
            await viewModel.load()
        }
        .onChange(of: viewModel.didComplete) { _, completed in
            if completed {
                dismiss()
            }
        }
        .alert("Error", isPresented: .constant(viewModel.errorMessage != nil && !viewModel.isLoading)) {
            Button("OK") {
                viewModel.errorMessage = nil
            }
        } message: {
            if let error = viewModel.errorMessage {
                Text(error)
            }
        }
    }

    // MARK: - Form

    private var formPanel: some View {
        Form {
            Section("Event Details") {
                TextField("Title", text: $viewModel.title)
                    .accessibilityIdentifier("eventDetailTitle")
                    .onChange(of: viewModel.title) { _, _ in
                        viewModel.scheduleSave()
                    }

                Toggle("All Day", isOn: $viewModel.allDay)
                    .onChange(of: viewModel.allDay) { _, _ in
                        viewModel.scheduleSave()
                    }

                if viewModel.allDay {
                    DatePicker("Date", selection: $viewModel.startDate, displayedComponents: .date)
                        .onChange(of: viewModel.startDate) { _, _ in
                            viewModel.scheduleSave()
                        }
                } else {
                    DatePicker("Start", selection: $viewModel.startDate)
                        .onChange(of: viewModel.startDate) { _, _ in
                            viewModel.scheduleSave()
                        }
                    DatePicker("End", selection: $viewModel.endDate)
                        .onChange(of: viewModel.endDate) { _, _ in
                            viewModel.scheduleSave()
                        }
                }

                TextField("Location", text: $viewModel.location)
                    .onChange(of: viewModel.location) { _, _ in
                        viewModel.scheduleSave()
                    }
            }

            Section("Description") {
                TextEditor(text: $viewModel.eventDescription)
                    .frame(minHeight: 100)
                    .onChange(of: viewModel.eventDescription) { _, _ in
                        viewModel.scheduleSave()
                    }
            }

            if viewModel.isSaving {
                Section {
                    HStack {
                        ProgressView()
                            .controlSize(.small)
                        Text("Saving...")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    // MARK: - Source Panel (iPad)

    private var sourcePanel: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("Source Email")
                    .font(.title3)
                    .fontWeight(.semibold)
                    .padding(.horizontal)
                    .padding(.top)

                if let sources = viewModel.event?.eventSources, !sources.isEmpty {
                    ForEach(sources) { source in
                        sourceCard(source)
                    }
                } else {
                    Text("No source information available.")
                        .foregroundStyle(.secondary)
                        .padding(.horizontal)
                }
            }
        }
        .background(Color(.systemGroupedBackground))
    }

    // MARK: - Source Disclosure (iPhone)

    private var sourceDisclosure: some View {
        Group {
            if let sources = viewModel.event?.eventSources, !sources.isEmpty {
                DisclosureGroup("Source Email") {
                    VStack(spacing: 12) {
                        ForEach(sources) { source in
                            sourceCard(source)
                        }
                    }
                }
                .padding()
            }
        }
    }

    // MARK: - Source Card

    @ViewBuilder
    private func sourceCard(_ source: EventSource) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            if let email = source.emails {
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(email.fromName ?? "Unknown Sender")
                            .font(.headline)
                        Text(email.fromEmail ?? "")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    if let dateSent = email.dateSent {
                        Text(dateSent, style: .date)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }

                if let subject = email.subject {
                    Text(subject)
                        .font(.subheadline)
                        .fontWeight(.medium)
                }
            }

            if let extractedData = source.extractedData,
               let quote = extractedData.sourceQuote {
                Text(quote)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .padding(8)
                    .background(Color(.tertiarySystemGroupedBackground))
                    .clipShape(RoundedRectangle(cornerRadius: 8))
            }

            HStack {
                Label(source.sourceType.rawValue.replacingOccurrences(of: "_", with: " ").capitalized,
                      systemImage: "tag")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
        .padding()
        .background(.regularMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .padding(.horizontal)
    }
}

#Preview {
    NavigationStack {
        EventDetailView(eventId: UUID())
    }
}
