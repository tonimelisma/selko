//
//  SettingsView.swift
//  Selko
//

import SwiftUI

struct SettingsView: View {
    @State private var viewModel = SettingsViewModel()

    var body: some View {
        Form {
            connectedAccountsSection
            calendarDefaultsSection
            accountSection
        }
        .navigationTitle("Settings")
        .task {
            await viewModel.load()
        }
        .refreshable {
            await viewModel.load()
        }
        .alert("Disconnect Account", isPresented: $viewModel.showDisconnectAlert) {
            Button("Cancel", role: .cancel) {}
            Button("Disconnect", role: .destructive) {
                Task { await viewModel.disconnect() }
            }
        } message: {
            if let provider = viewModel.providerToDisconnect {
                Text("Are you sure you want to disconnect \(viewModel.providerDisplayName(provider))? You will need to reconnect to continue using this integration.")
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

    // MARK: - Connected Accounts

    private var connectedAccountsSection: some View {
        Section("Connected Accounts") {
            integrationRow(provider: .gmail)
            integrationRow(provider: .googleCalendar)
        }
    }

    @ViewBuilder
    private func integrationRow(provider: IntegrationProvider) -> some View {
        let integration = viewModel.integration(for: provider)
        let isActive = integration?.isActive ?? false

        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(viewModel.providerDisplayName(provider))
                    .font(.body)

                if let email = integration?.providerEmail {
                    Text(email)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } else if let integration = integration {
                    Text(integration.status.rawValue.capitalized)
                        .font(.caption)
                        .foregroundStyle(integration.isActive ? .green : .orange)
                }
            }

            Spacer()

            if isActive {
                Menu {
                    Button(role: .destructive) {
                        viewModel.confirmDisconnect(provider: provider)
                    } label: {
                        Label("Disconnect", systemImage: "trash")
                    }
                } label: {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                }
            } else {
                Button("Connect") {
                    connectProvider(provider)
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
            }
        }
    }

    // MARK: - Calendar Defaults

    @ViewBuilder
    private var calendarDefaultsSection: some View {
        let calendarConnected = viewModel.integrations.contains { $0.provider == .googleCalendar && $0.isActive }

        if calendarConnected {
            Section("Calendar Defaults") {
                if viewModel.calendars.isEmpty {
                    if viewModel.isLoading {
                        HStack {
                            ProgressView()
                                .controlSize(.small)
                            Text("Loading calendars...")
                                .foregroundStyle(.secondary)
                        }
                    } else {
                        Text("No calendars available")
                            .foregroundStyle(.secondary)
                    }
                } else {
                    Picker("Default Calendar", selection: $viewModel.selectedCalendarId) {
                        ForEach(viewModel.calendars) { calendar in
                            HStack {
                                Text(calendar.name)
                                if calendar.isPrimary {
                                    Text("(Primary)")
                                        .foregroundStyle(.secondary)
                                }
                            }
                            .tag(calendar.id)
                        }
                    }
                    .onChange(of: viewModel.selectedCalendarId) { _, _ in
                        Task { await viewModel.updateDefaultCalendar() }
                    }
                }
            }
        }
    }

    // MARK: - Account

    private var accountSection: some View {
        Section("Account") {
            Button(role: .destructive) {
                Task { await viewModel.signOut() }
            } label: {
                HStack {
                    Spacer()
                    Text("Sign Out")
                    Spacer()
                }
            }
        }
    }

    // MARK: - Actions

    private func connectProvider(_ provider: IntegrationProvider) {
        let backendAPI = DependencyContainer.shared.backendAPI
        let urlString: String

        switch provider {
        case .gmail:
            urlString = backendAPI.getGmailAuthUrl(redirectUri: nil)
        case .googleCalendar:
            urlString = backendAPI.getCalendarAuthUrl(redirectUri: nil)
        case .googlePhotos:
            return // Not supported yet
        }

        if let url = URL(string: urlString) {
            UIApplication.shared.open(url)
        }
    }
}

#Preview {
    NavigationStack {
        SettingsView()
    }
}
