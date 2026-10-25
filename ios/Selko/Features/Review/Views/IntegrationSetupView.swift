//
//  IntegrationSetupView.swift
//  Selko
//

import SwiftUI

/// First-run onboarding. One Google consent connects both Gmail and Google
/// Calendar, so the screen offers a single Google row.
struct IntegrationSetupView: View {
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

            googleRow
                .padding(.horizontal)

            Spacer()
            Spacer()
        }
        .padding()
        .background(Color.selkoPaper.ignoresSafeArea())
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("integrationSetupView")
    }

    private var googleRow: some View {
        HStack(spacing: 12) {
            Image(systemName: "envelope.fill")
                .font(SelkoTypography.sectionTitle)
                .foregroundStyle(Color.selkoMuted)
                .frame(width: 40)

            VStack(alignment: .leading, spacing: 2) {
                Text("Google")
                    .font(SelkoTypography.title)
                Text("Find events in Gmail and sync them to Google Calendar")
                    .font(SelkoTypography.caption)
                    .foregroundStyle(Color.selkoMuted)
            }

            Spacer()

            Button("Connect") {
                Task { await openAuth(for: .gmail) }
            }
            .buttonStyle(.selko(.primary))
            .disabled(authorizer.connectingProvider != nil)
            .accessibilityLabel("Connect Google")
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
    IntegrationSetupView()
}
