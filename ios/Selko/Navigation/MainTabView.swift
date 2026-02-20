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
                ReviewQueueView()
                    .navigationDestination(for: UUID.self) { eventId in
                        EventDetailView(eventId: eventId)
                    }
            }
            .tabItem {
                Label("Review", systemImage: "list.bullet")
            }
            .tag(Tab.review)

            NavigationStack {
                HistoryView()
            }
            .tabItem {
                Label("History", systemImage: "clock.arrow.circlepath")
            }
            .tag(Tab.history)

            NavigationStack {
                SettingsView()
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
    }
}

#Preview {
    MainTabView(router: AppRouter())
}
