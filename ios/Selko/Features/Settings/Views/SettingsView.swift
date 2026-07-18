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
                emailFoldersSection
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

        if isActive {
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 8) {
                    Text(viewModel.providerDisplayName(provider))
                        .font(SelkoTypography.title)
                        .foregroundStyle(Color.selkoInk)
                    Spacer()
                    SelkoStatusIndicator(text: "Connected", systemImage: "checkmark.circle", tone: .success)
                }

                HStack(spacing: 8) {
                    if let email = integration?.providerEmail {
                        Text(email)
                            .font(SelkoTypography.caption)
                            .foregroundStyle(Color.selkoFaint)
                            .lineLimit(1)
                            .truncationMode(.middle)
                    }
                    Spacer()
                    Button(role: .destructive) {
                        viewModel.confirmDisconnect(provider: provider)
                    } label: {
                        Text("Disconnect")
                    }
                    .buttonStyle(.selko(.destructiveOutline))
                }
            }
        } else {
            HStack(spacing: 8) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(viewModel.providerDisplayName(provider))
                        .font(SelkoTypography.title)
                        .foregroundStyle(Color.selkoInk)

                    if let integration {
                        Text(integration.status.rawValue.capitalized)
                            .font(SelkoTypography.caption)
                            .foregroundStyle(Color.selkoWarningText)
                    }
                }
                Spacer()
                Button("Connect") {
                    connectProvider(provider)
                }
                .buttonStyle(.selko(.primary))
                .accessibilityLabel("Connect \(viewModel.providerDisplayName(provider))")
            }
        }
    }

    // MARK: - Email Folders

    @ViewBuilder
    private var emailFoldersSection: some View {
        let providers = [IntegrationProvider.gmail, .outlook]
        let connectedProviders = providers.filter {
            viewModel.integration(for: $0)?.isActive == true
        }

        if !connectedProviders.isEmpty {
            Section {
                ForEach(connectedProviders, id: \.self) { provider in
                    Text(viewModel.providerDisplayName(provider))
                        .font(SelkoTypography.title)
                        .foregroundStyle(Color.selkoInk)

                    if let loadError = viewModel.folderLoadErrors[provider] {
                        HStack(alignment: .firstTextBaseline, spacing: 8) {
                            Text(loadError)
                                .font(SelkoTypography.caption)
                                .foregroundStyle(Color.selkoError)
                            Spacer()
                            Button("Retry") {
                                Task { await viewModel.reloadEmailFolders(provider: provider) }
                            }
                            .buttonStyle(.selko(.tertiary))
                            .foregroundStyle(Color.selkoError)
                            .accessibilityIdentifier("folderLoadRetry_\(provider.rawValue)")
                        }
                    } else {
                        ForEach(viewModel.folders(for: provider)) { folder in
                            folderRow(provider: provider, folder: folder)
                        }
                    }
                }
            } header: {
                Text("Email Folders")
            } footer: {
                Text("Included folders are scanned for calendar-relevant messages.")
            }
            .accessibilityIdentifier("emailFoldersSection")
        }
    }

    private func folderRow(provider: IntegrationProvider, folder: EmailFolderPreference) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Toggle(isOn: Binding(
                get: { viewModel.folders(for: provider).first(where: { $0.id == folder.id })?.isIncluded ?? folder.isIncluded },
                set: { included in
                    Task { await viewModel.updateFolder(provider: provider, folderId: folder.id, isIncluded: included) }
                }
            )) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(folder.fullPath)
                        .font(SelkoTypography.title)
                        .foregroundStyle(Color.selkoInk)
                    Text(folder.isIncluded ? "Included" : "Excluded")
                        .font(SelkoTypography.caption.weight(.semibold))
                        .foregroundStyle(Color.selkoMuted)
                    if folder.classificationDecision == "exclude", let reason = folder.classificationReason {
                        Text("Recommendation: \(reason)")
                            .font(SelkoTypography.caption)
                            .foregroundStyle(Color.selkoFaint)
                    }
                }
            }
            .toggleStyle(.switch)
            .tint(Color.accentColor)
            .disabled(viewModel.updatingFolderIds.contains(folder.id))
            .accessibilityIdentifier("folderToggle_\(folder.id)")

            if viewModel.updatingFolderIds.contains(folder.id) {
                ProgressView()
                    .controlSize(.small)
                    .accessibilityLabel("Saving folder preference")
            }

            if let failure = viewModel.folderErrors[folder.id] {
                HStack(spacing: 8) {
                    Text(failure.message)
                        .font(SelkoTypography.caption)
                        .foregroundStyle(Color.selkoError)
                    Button("Retry") {
                        Task { await viewModel.retryFolderUpdate(provider: provider, folderId: folder.id) }
                    }
                    .buttonStyle(.selko(.tertiary))
                    .foregroundStyle(Color.selkoError)
                    .accessibilityIdentifier("folderRetry_\(folder.id)")
                }
                .accessibilityElement(children: .combine)
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
            if !email.isEmpty {
                LabeledContent("Email", value: email)
                    .foregroundStyle(Color.selkoInk)
            }
            Button(role: .destructive) {
                Task { await viewModel.signOut() }
            } label: {
                HStack {
                    Spacer()
                    Text("Log out")
                    Spacer()
                }
            }
            .buttonStyle(.selko(.destructiveOutline))
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
