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
        VStack(spacing: 20) {
            Spacer()

            Text("Selko")
                .font(.largeTitle)
                .fontWeight(.bold)
                .foregroundStyle(Color.accentColor)

            Text("Clear your mind.")
                .font(.subheadline)
                .foregroundStyle(.primary.opacity(0.7))

            Spacer()

            VStack(spacing: 16) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Email")
                        .font(.subheadline)
                        .fontWeight(.medium)
                    TextField("", text: $viewModel.email, prompt: Text("you@example.com").foregroundStyle(.secondary))
                        .textFieldStyle(.roundedBorder)
                        .textContentType(.emailAddress)
                        .keyboardType(.emailAddress)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                        .accessibilityLabel("Email address")
                        .accessibilityIdentifier("emailField")
                }

                VStack(alignment: .leading, spacing: 4) {
                    Text("Password")
                        .font(.subheadline)
                        .fontWeight(.medium)
                    SecureField("Your password", text: $viewModel.password)
                        .textFieldStyle(.roundedBorder)
                        .textContentType(.password)
                        .accessibilityLabel("Password")
                        .accessibilityIdentifier("passwordField")
                }

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
                        Text("Sign in")
                    }
                }
                .frame(maxWidth: .infinity, minHeight: 44)
                .background(Color.accentColor)
                .foregroundColor(.white)
                .fontWeight(.medium)
                .clipShape(RoundedRectangle(cornerRadius: 2))
                .disabled(viewModel.isLoading)
                .accessibilityIdentifier("signInButton")
            }

            HStack(spacing: 4) {
                Text("Don't have an account?")
                    .font(.subheadline)
                Button("Sign up") {
                    showRegister = true
                }
                .font(.subheadline)
                .frame(minWidth: 44, minHeight: 44)
                .accessibilityHint("Opens sign up form")
                .accessibilityIdentifier("createAccountButton")
            }
            .padding(.vertical, 8)

            Spacer()
        }
        .padding()
        .fullScreenCover(isPresented: $showRegister) {
            RegisterView()
        }
    }
}

#Preview {
    LoginView()
}
