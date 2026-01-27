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
                } else if router.isAuthenticated {
                    HomeView()
                } else {
                    LoginView()
                }
            }
        }
    }
}
