import SwiftUI

struct ConnectionRecoveryView: View {
    let integrations: [Integration]

    @State private var authorizer = OAuthAuthorizer()
    @Environment(\.openURL) private var openURL

    private var emailConnected: Bool {
        integrations.contains {
            ($0.provider == .gmail || $0.provider == .outlook) && $0.isActive
        }
    }

    private var calendarConnected: Bool {
        integrations.contains { $0.provider == .googleCalendar && $0.isActive }
    }

    private var recoveryProviders: [IntegrationProvider] {
        let providers: [IntegrationProvider]
        if !emailConnected {
            providers = [.gmail, .outlook] + (calendarConnected ? [] : [.googleCalendar])
        } else if !calendarConnected {
            let inactiveEmailProviders = integrations
                .filter {
                    ($0.provider == .gmail || $0.provider == .outlook) && !$0.isActive
                }
                .map(\.provider)
            providers = [.googleCalendar] + inactiveEmailProviders
        } else {
            providers = integrations.filter { !$0.isActive }.map(\.provider)
        }
        return providers.reduce(into: []) { result, provider in
            guard provider != .googlePhotos, !result.contains(provider) else { return }
            result.append(provider)
        }
    }

    private var title: String {
        if !emailConnected { return "Reconnect an email account" }
        if !calendarConnected { return "Reconnect Google Calendar" }
        return "A connection needs attention"
    }

    private var message: String {
        if !emailConnected {
            return "New email suggestions are paused. Your existing suggestions and history are still available."
        }
        if !calendarConnected {
            return "You can keep reviewing, editing, and rejecting suggestions. Reconnect before accepting one."
        }
        return "Selko is still working through another connected account. Reconnect this provider when convenient."
    }

    var body: some View {
        if !recoveryProviders.isEmpty {
            VStack(alignment: .leading, spacing: 14) {
                if let error = authorizer.errorMessage {
                    Text(error)
                        .font(SelkoTypography.body)
                        .foregroundStyle(Color.selkoError)
                        .accessibilityIdentifier("connectionRecoveryError")
                }

                HStack(alignment: .top, spacing: 12) {
                    Image(systemName: "exclamationmark.triangle")
                        .foregroundStyle(Color.selkoWarningText)
                        .accessibilityHidden(true)
                    VStack(alignment: .leading, spacing: 4) {
                        Text(title)
                            .font(SelkoTypography.title)
                            .foregroundStyle(Color.selkoInk)
                        Text(message)
                            .font(SelkoTypography.body)
                            .foregroundStyle(Color.selkoMuted)
                    }
                }

                ForEach(Array(recoveryProviders.enumerated()), id: \.element.rawValue) { index, provider in
                    Button(buttonLabel(for: provider)) {
                        Task { await openAuth(for: provider) }
                    }
                    .buttonStyle(.selko(index == 0 ? .primary : .secondary))
                    .frame(maxWidth: .infinity)
                    .disabled(authorizer.connectingProvider != nil)
                }

                Text("You can also manage connections in Settings.")
                    .font(SelkoTypography.caption)
                    .foregroundStyle(Color.selkoFaint)
            }
            .padding(16)
            .background(Color.selkoSurface)
            .clipShape(SelkoShape.card)
            .overlay(SelkoShape.card.stroke(Color.selkoWarning, lineWidth: 1))
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("connectionRecoveryView")
        }
    }

    private func buttonLabel(for provider: IntegrationProvider) -> String {
        let verb = integrations.contains(where: { $0.provider == provider && !$0.isActive })
            ? "Reconnect"
            : "Connect"
        return "\(verb) \(providerName(provider))"
    }

    private func providerName(_ provider: IntegrationProvider) -> String {
        switch provider {
        case .gmail: "Gmail"
        case .outlook: "Outlook"
        case .googleCalendar: "Google Calendar"
        case .googlePhotos: "Google Photos"
        }
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
