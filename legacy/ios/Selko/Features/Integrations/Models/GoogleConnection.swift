//
//  GoogleConnection.swift
//  Selko
//

import Foundation

/// The single Google connection behind the `gmail` and `google_calendar` rows.
///
/// One Google consent connects both products and the callback stores the
/// shared token in both rows, so they connect, expire and disconnect together.
/// The client shows them as one card whose state derives from both rows.
struct GoogleConnection: Equatable {
    enum State: Equatable {
        case notConnected
        case connected
        /// One product is active and the other has no row: the user unticked
        /// its scope on Google's consent screen.
        case partial(missing: IntegrationProvider)
        /// A row exists but is expired, revoked or errored.
        case needsReconnect(IntegrationStatus)
    }

    static let providers: [IntegrationProvider] = [.gmail, .googleCalendar]

    let state: State
    let rows: [Integration]

    var email: String? { rows.lazy.compactMap(\.providerEmail).first }

    init(integrations: [Integration]) {
        let gmail = integrations.first { $0.provider == .gmail }
        let calendar = integrations.first { $0.provider == .googleCalendar }
        rows = [gmail, calendar].compactMap { $0 }

        if rows.isEmpty {
            state = .notConnected
        } else if let inactive = rows.first(where: { !$0.isActive }) {
            state = .needsReconnect(inactive.status)
        } else if gmail != nil, calendar != nil {
            state = .connected
        } else {
            state = .partial(missing: gmail == nil ? .gmail : .googleCalendar)
        }
    }
}
