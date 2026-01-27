//
//  HomeView.swift
//  Selko
//
//  Created by Claude on 1/26/26.
//

import SwiftUI

struct HomeView: View {
    @State private var viewModel = HomeViewModel()

    var body: some View {
        NavigationStack {
            VStack(spacing: 24) {
                Spacer()

                Image(systemName: "hand.wave.fill")
                    .font(.system(size: 60))
                    .foregroundStyle(.tint)

                if viewModel.isLoading {
                    ProgressView()
                } else {
                    Text("Hello, \(viewModel.userEmail.isEmpty ? "User" : viewModel.userEmail)!")
                        .font(.title)
                        .multilineTextAlignment(.center)
                        .accessibilityIdentifier("welcomeMessage")
                }

                Text("Welcome to Selko")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)

                Spacer()

                if let error = viewModel.errorMessage {
                    Text(error)
                        .foregroundStyle(.red)
                        .font(.caption)
                }
            }
            .padding()
            .navigationTitle("Home")
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button("Sign Out") {
                        Task {
                            await viewModel.signOut()
                        }
                    }
                    .accessibilityIdentifier("signOutButton")
                }
            }
            .task {
                await viewModel.loadUser()
            }
        }
    }
}

#Preview {
    HomeView()
}
