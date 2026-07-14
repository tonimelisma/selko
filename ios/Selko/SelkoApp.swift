//
//  SelkoApp.swift
//  Selko
//
//  Created by Toni Melisma on 1/26/26.
//

import SwiftUI

@main
struct SelkoApp: App {
    @State private var router = AppRouter()

    var body: some Scene {
        WindowGroup {
            Group {
                if router.isLoading {
                    ProgressView("Loading...")
                        .tint(Color.accentColor)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .background(Color.selkoPaper.ignoresSafeArea())
                } else if router.isAuthenticated {
                    MainTabView(router: router)
                } else {
                    LoginView()
                }
            }
            .onOpenURL { url in
                router.handleDeepLink(url)
            }
        }
    }
}
