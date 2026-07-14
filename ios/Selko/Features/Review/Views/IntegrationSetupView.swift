//
//  IntegrationSetupView.swift
//  Selko
//

import SwiftUI

struct IntegrationSetupView: View {
    let gmailConnected: Bool
    let calendarConnected: Bool

    private let backendAPI: BackendAPIProtocol = DependencyContainer.shared.backendAPI
    @Environment(\.openURL) private var openURL

    var body: some View {
        VStack(spacing: 24) {
            Spacer()

            SelkoLogoMark(size: 60)

            Text("Welcome to Selko!")
                .font(SelkoTypography.sectionTitle)
                .foregroundStyle(Color.selkoInk)

            Text("Connect your Google account to start reviewing calendar events extracted from your emails.")
                .font(SelkoTypography.body)
                .foregroundStyle(Color.selkoMuted)
                .multilineTextAlignment(.center)
                .padding(.horizontal)

            VStack(spacing: 16) {
                integrationRow(
                    title: "Gmail",
                    description: "Read your emails to find events",
                    systemImage: "envelope.fill",
                    isConnected: gmailConnected
                ) {
                    openGmailAuth()
                }

                integrationRow(
                    title: "Google Calendar",
                    description: "Sync approved events to your calendar",
                    systemImage: "calendar",
                    isConnected: calendarConnected
                ) {
                    openCalendarAuth()
                }
            }
            .padding(.horizontal)

            Spacer()
            Spacer()
        }
        .padding()
        .background(Color.selkoPaper.ignoresSafeArea())
        .accessibilityIdentifier("integrationSetupView")
    }

    @ViewBuilder
    private func integrationRow(
        title: String,
        description: String,
        systemImage: String,
        isConnected: Bool,
        action: @escaping () -> Void
    ) -> some View {
        HStack(spacing: 12) {
            Image(systemName: systemImage)
                .font(SelkoTypography.sectionTitle)
                .foregroundStyle(isConnected ? Color.selkoSuccess : Color.selkoMuted)
                .frame(width: 40)

            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(SelkoTypography.title)
                Text(description)
                    .font(SelkoTypography.caption)
                    .foregroundStyle(Color.selkoMuted)
            }

            Spacer()

            if isConnected {
                Image(systemName: "checkmark.circle.fill")
                    .foregroundStyle(Color.selkoSuccess)
            } else {
                Button("Connect") {
                    action()
                }
                .buttonStyle(.borderedProminent)
                .tint(Color.accentColor)
            }
        }
        .padding()
        .padding(.vertical, 2)
        .selkoCard()
    }

    private func openGmailAuth() {
        let urlString = backendAPI.getGmailAuthUrl(redirectUri: nil)
        if let url = URL(string: urlString) {
            openURL(url)
        }
    }

    private func openCalendarAuth() {
        let urlString = backendAPI.getCalendarAuthUrl(redirectUri: nil)
        if let url = URL(string: urlString) {
            openURL(url)
        }
    }
}

#Preview {
    IntegrationSetupView(gmailConnected: true, calendarConnected: false)
}
