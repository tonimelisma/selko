import SwiftUI

struct ConnectionRecoveryView: View {
    let integrations: [Integration]

    @State private var authorizer = OAuthAuthorizer()
    @State private var recovery: IntegrationRecovery?
    @State private var justCaughtUp = false
    @Environment(\.openURL) private var openURL

    private struct CatchUpDisplay {
        let icon: String
        let tone: Color
        let title: String
        let message: String
    }

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

    private var recoveryDisplay: CatchUpDisplay? {
        guard let recovery else { return nil }
        switch recovery.status {
        case .pending, .processing:
            return CatchUpDisplay(
                icon: "arrow.triangle.2.circlepath",
                tone: Color.selkoWarningText,
                title: "Starting catch-up…",
                message: "Selko is resuming calendar sync after your reconnect."
            )
        case .waiting:
            return CatchUpDisplay(
                icon: "arrow.triangle.2.circlepath",
                tone: Color.selkoWarningText,
                title: "Catching up — \(recovery.remainingCount ?? 0) remaining",
                message: "Selko is resuming calendar sync after your reconnect. You can keep reviewing and editing."
            )
        case .completed:
            return justCaughtUp
                ? CatchUpDisplay(
                    icon: "checkmark",
                    tone: Color.selkoSuccessText,
                    title: "Caught up",
                    message: "Calendar sync is back to normal."
                )
                : nil
        case .completedWithErrors:
            return CatchUpDisplay(
                icon: "exclamationmark.triangle",
                tone: Color.selkoWarningText,
                title: "Caught up with \(recovery.needingAttentionCount) items needing attention",
                message: "Most events synced, but \(recovery.needingAttentionCount) didn't make it. Review them from Settings."
            )
        case .failed:
            return CatchUpDisplay(
                icon: "exclamationmark.triangle",
                tone: Color.selkoError,
                title: "Catch-up didn't finish",
                message: "Reconnect Google Calendar to try again."
            )
        case .superseded:
            return nil
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
        VStack(spacing: 12) {
            if let display = recoveryDisplay {
                catchUpCard(display)
            }

            if !recoveryProviders.isEmpty {
                reconnectCard
            }
        }
        .task {
            await pollRecovery()
        }
    }

    // MARK: - Catch-up card

    private func catchUpCard(_ display: CatchUpDisplay) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: display.icon)
                    .foregroundStyle(display.tone)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 4) {
                    Text(display.title)
                        .font(SelkoTypography.title)
                        .foregroundStyle(Color.selkoInk)
                    Text(display.message)
                        .font(SelkoTypography.body)
                        .foregroundStyle(Color.selkoMuted)
                }
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.selkoSurface)
        .clipShape(SelkoShape.card)
        .overlay(SelkoShape.card.stroke(Color.selkoWarning, lineWidth: 1))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("catchUpView")
    }

    // MARK: - Reconnect card

    private var reconnectCard: some View {
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

            SelkoPeerActionGroup {
                ForEach(recoveryProviders, id: \.rawValue) { provider in
                    Button(buttonLabel(for: provider)) {
                        Task { await openAuth(for: provider) }
                    }
                    .buttonStyle(.selko(.primary))
                    .frame(maxWidth: .infinity)
                    .disabled(authorizer.connectingProvider != nil)
                }
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

    private func pollRecovery() async {
        while !Task.isCancelled {
            let previous = recovery
            recovery = try? await DependencyContainer.shared.integrationService.fetchCalendarRecovery()
            if let previous, previous.status != .completed, recovery?.status == .completed {
                justCaughtUp = true
                try? await Task.sleep(for: .seconds(4))
                justCaughtUp = false
            }
            if let recovery, recovery.isActive {
                try? await Task.sleep(for: .seconds(5))
            } else {
                break
            }
        }
    }
}
