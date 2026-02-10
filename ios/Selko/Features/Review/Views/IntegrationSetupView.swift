//
//  IntegrationSetupView.swift
//  Selko
//

import SwiftUI

struct IntegrationSetupView: View {
    let gmailConnected: Bool
    let calendarConnected: Bool

    private let backendAPI: BackendAPIProtocol = DependencyContainer.shared.backendAPI

    var body: some View {
        VStack(spacing: 32) {
            Spacer()

            Image(systemName: "envelope.badge.person.crop")
                .font(.system(size: 60))
                .foregroundStyle(.tint)

            Text("Welcome to Selko!")
                .font(.title)
                .fontWeight(.bold)

            Text("Connect your Google account to start reviewing calendar events extracted from your emails.")
                .font(.body)
                .foregroundStyle(.secondary)
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
        HStack(spacing: 16) {
            Image(systemName: systemImage)
                .font(.title2)
                .foregroundStyle(isConnected ? Color.selkoSuccess : .secondary)
                .frame(width: 40)

            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.headline)
                Text(description)
                    .font(.caption)
                    .foregroundStyle(.secondary)
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
            }
        }
        .padding()
        .background(.regularMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 2))
    }

    private func openGmailAuth() {
        let urlString = backendAPI.getGmailAuthUrl(redirectUri: nil)
        if let url = URL(string: urlString) {
            UIApplication.shared.open(url)
        }
    }

    private func openCalendarAuth() {
        let urlString = backendAPI.getCalendarAuthUrl(redirectUri: nil)
        if let url = URL(string: urlString) {
            UIApplication.shared.open(url)
        }
    }
}

#Preview {
    IntegrationSetupView(gmailConnected: true, calendarConnected: false)
}
