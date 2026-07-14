//
//  MainTabView.swift
//  Selko
//

import SwiftUI

struct MainTabView: View {
    @Bindable var router: AppRouter
    @State private var reviewPath = NavigationPath()

    var body: some View {
        TabView(selection: $router.selectedTab) {
            NavigationStack(path: $reviewPath) {
                ReviewQueueView(email: router.userEmail)
                    .navigationDestination(for: UUID.self) { eventId in
                        EventDetailView(eventId: eventId)
                    }
            }
            .tabItem {
                Label("Review", systemImage: "list.bullet")
            }
            .tag(Tab.review)

            NavigationStack {
                HistoryView(email: router.userEmail)
            }
            .tabItem {
                Label("History", systemImage: "clock.arrow.circlepath")
            }
            .tag(Tab.history)

            NavigationStack {
                SettingsView(email: router.userEmail)
            }
            .tabItem {
                Label("Settings", systemImage: "gear")
            }
            .tag(Tab.settings)
        }
        .onChange(of: router.pendingEventId) { _, newEventId in
            if let eventId = newEventId {
                // Navigate to the event detail within the Review tab
                reviewPath.append(eventId)
                router.pendingEventId = nil
            }
        }
        .tint(Color.accentColor)
        .toolbarBackground(Color.selkoSurface, for: .tabBar)
        .toolbarBackground(.visible, for: .tabBar)
    }
}

#Preview {
    MainTabView(router: AppRouter())
}
