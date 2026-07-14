//
//  SettingsView.swift
//  Selko
//

import SwiftUI

struct SettingsView: View {
    let email: String
    @State private var viewModel = SettingsViewModel()
    @State private var showAuthError = false

    init(email: String = "") {
        self.email = email
    }

    var body: some View {
        VStack(spacing: 0) {
            SelkoScreenHeader(title: "Settings", subtitle: "Keep your accounts, folders, and rules in sync.", email: email)
            Form {
                connectedAccountsSection
                calendarDefaultsSection
                senderRulesSection
                accountSection
            }
            .scrollContentBackground(.hidden)
            .background(Color.selkoPaper)
        }
        .background(Color.selkoPaper.ignoresSafeArea())
        .navigationTitle("Settings")
        .navigationBarTitleDisplayMode(.inline)
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
        .alert("Connection Error", isPresented: $showAuthError) {
            Button("OK", role: .cancel) { }
        } message: {
            Text(String(localized: "settings.authErrorMessage"))
        }
    }

    // MARK: - Connected Accounts

    private var connectedAccountsSection: some View {
        Section("Connected Accounts") {
            integrationRow(provider: .gmail)
            integrationRow(provider: .outlook)
            integrationRow(provider: .googleCalendar)
        }
        .accessibilityIdentifier("connectedAccountsSection")
    }

    @ViewBuilder
    private func integrationRow(provider: IntegrationProvider) -> some View {
        let integration = viewModel.integration(for: provider)
        let isActive = integration?.isActive ?? false

        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(viewModel.providerDisplayName(provider))
                    .font(SelkoTypography.title)
                    .foregroundStyle(Color.selkoInk)

                if let email = integration?.providerEmail {
                    Text(email)
                        .font(SelkoTypography.caption)
                        .foregroundStyle(Color.selkoFaint)
                } else if let integration = integration {
                    Text(integration.status.rawValue.capitalized)
                        .font(SelkoTypography.caption)
                        .foregroundStyle(integration.isActive ? Color.selkoSuccess : Color.selkoWarning)
                }
            }

            Spacer()

            if isActive {
                Image(systemName: "checkmark.circle.fill")
                    .foregroundStyle(Color.selkoSuccess)
                    .accessibilityLabel("Connected")

                    Button(role: .destructive) {
                        viewModel.confirmDisconnect(provider: provider)
                    } label: {
                        Text("Disconnect")
                        .font(SelkoTypography.caption.weight(.bold))
                }
                .buttonStyle(.bordered)
                    .tint(Color.selkoError)
            } else {
                Button("Connect") {
                    connectProvider(provider)
                }
                .buttonStyle(.bordered)
                .tint(Color.accentColor)
                .accessibilityLabel("Connect \(viewModel.providerDisplayName(provider))")
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
                                .foregroundStyle(Color.selkoMuted)
                        }
                    } else {
                        Text("Connect Google Calendar to configure calendar defaults.")
                            .foregroundStyle(Color.selkoMuted)
                    }
                } else {
                    Picker("Default Calendar", selection: $viewModel.selectedCalendarId) {
                        ForEach(viewModel.calendars) { calendar in
                            HStack {
                                Text(calendar.name)
                                if calendar.isPrimary {
                                    Text("(Primary)")
                                        .foregroundStyle(Color.selkoMuted)
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

    // MARK: - Sender Rules

    private var senderRulesSection: some View {
        Section {
            NavigationLink {
                SenderRulesView()
            } label: {
                Label("Sender Rules", systemImage: "shield.lefthalf.filled")
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
                    Text("Log out")
                    Spacer()
                }
            }
            .buttonStyle(.bordered)
            .tint(Color.selkoError)
            .accessibilityIdentifier("signOutButton")
        }
    }

    // MARK: - Actions

    private func connectProvider(_ provider: IntegrationProvider) {
        let backendAPI = DependencyContainer.shared.backendAPI
        let urlString: String

        switch provider {
        case .gmail:
            urlString = backendAPI.getGmailAuthUrl(redirectUri: nil)
        case .outlook:
            urlString = backendAPI.getOutlookAuthUrl(redirectUri: nil)
        case .googleCalendar:
            urlString = backendAPI.getCalendarAuthUrl(redirectUri: nil)
        case .googlePhotos:
            return
        }

        if let url = URL(string: urlString) {
            UIApplication.shared.open(url) { success in
                if !success {
                    showAuthError = true
                }
            }
        }
    }
}

#Preview {
    NavigationStack {
        SettingsView()
    }
}
