//
//  IntegrationSetupView.swift
//  Selko
//

import SwiftUI

struct IntegrationSetupView: View {
    let gmailConnected: Bool
    let calendarConnected: Bool

    @State private var authorizer = OAuthAuthorizer()
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

            if let error = authorizer.errorMessage {
                Text(error)
                    .font(SelkoTypography.body)
                    .foregroundStyle(Color.selkoError)
                    .multilineTextAlignment(.center)
                    .accessibilityIdentifier("integrationSetupOAuthError")
            }

            VStack(spacing: 16) {
                integrationRow(
                    title: "Gmail",
                    description: "Read your emails to find events",
                    systemImage: "envelope.fill",
                    isConnected: gmailConnected
                ) {
                    Task { await openAuth(for: .gmail) }
                }

                integrationRow(
                    title: "Google Calendar",
                    description: "Sync approved events to your calendar",
                    systemImage: "calendar",
                    isConnected: calendarConnected
                ) {
                    Task { await openAuth(for: .googleCalendar) }
                }
            }
            .padding(.horizontal)

            Spacer()
            Spacer()
        }
        .padding()
        .background(Color.selkoPaper.ignoresSafeArea())
        .accessibilityElement(children: .contain)
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
                SelkoStatusIndicator(text: "Connected", systemImage: "checkmark.circle", tone: .success)
            } else {
                Button("Connect") {
                    action()
                }
                .buttonStyle(.selko(.primary))
                .disabled(authorizer.connectingProvider != nil)
            }
        }
        .padding()
        .padding(.vertical, 2)
        .selkoCard()
    }

    private func openAuth(for provider: IntegrationProvider) async {
        if let url = await authorizer.authorizationURL(for: provider) {
            openURL(url) { accepted in
                if !accepted {
                    authorizer.reportOpenFailure()
                }
            }
        }
    }
}

#Preview {
    IntegrationSetupView(gmailConnected: true, calendarConnected: false)
}
