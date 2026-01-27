//
//  LoginView.swift
//  Selko
//
//  Created by Claude on 1/26/26.
//

import SwiftUI

struct LoginView: View {
    @State private var viewModel = LoginViewModel()
    @State private var showRegister = false

    var body: some View {
        VStack(spacing: 24) {
            Spacer()

            Text("Selko")
                .font(.largeTitle)
                .fontWeight(.bold)

            Text("Your AI-powered personal assistant")
                .font(.subheadline)
                .foregroundStyle(.secondary)

            Spacer()

            VStack(spacing: 16) {
                TextField("Email", text: $viewModel.email)
                    .textFieldStyle(.roundedBorder)
                    .textContentType(.emailAddress)
                    .keyboardType(.emailAddress)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
                    .accessibilityIdentifier("emailField")

                SecureField("Password", text: $viewModel.password)
                    .textFieldStyle(.roundedBorder)
                    .textContentType(.password)
                    .accessibilityIdentifier("passwordField")

                if let error = viewModel.errorMessage {
                    Text(error)
                        .foregroundStyle(.red)
                        .font(.caption)
                        .multilineTextAlignment(.center)
                        .accessibilityIdentifier("errorMessage")
                }

                Button {
                    Task {
                        await viewModel.login()
                    }
                } label: {
                    if viewModel.isLoading {
                        ProgressView()
                            .progressViewStyle(.circular)
                            .tint(.white)
                    } else {
                        Text("Sign In")
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(viewModel.isLoading)
                .accessibilityIdentifier("signInButton")
            }

            Spacer()

            Button("Create Account") {
                showRegister = true
            }
            .accessibilityIdentifier("createAccountButton")

            Spacer()
        }
        .padding()
        .sheet(isPresented: $showRegister) {
            RegisterView()
        }
    }
}

#Preview {
    LoginView()
}
