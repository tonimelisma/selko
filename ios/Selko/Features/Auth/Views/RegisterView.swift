//
//  RegisterView.swift
//  Selko
//
//  Created by Claude on 1/26/26.
//

import SwiftUI

struct RegisterView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var viewModel = RegisterViewModel()

    var body: some View {
        NavigationStack {
            VStack(spacing: 20) {
                Spacer()

                Text("Sign up")
                    .font(.largeTitle)
                    .fontWeight(.bold)

                VStack(spacing: 16) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Email")
                            .font(.subheadline)
                            .fontWeight(.medium)
                        TextField("you@example.com", text: $viewModel.email)
                            .textFieldStyle(.roundedBorder)
                            .textContentType(.emailAddress)
                            .keyboardType(.emailAddress)
                            .autocorrectionDisabled()
                            .textInputAutocapitalization(.never)
                            .accessibilityIdentifier("registerEmailField")
                    }

                    VStack(alignment: .leading, spacing: 4) {
                        Text("Password")
                            .font(.subheadline)
                            .fontWeight(.medium)
                        SecureField("Choose a password", text: $viewModel.password)
                            .textFieldStyle(.roundedBorder)
                            .textContentType(.newPassword)
                            .accessibilityIdentifier("registerPasswordField")
                    }

                    VStack(alignment: .leading, spacing: 4) {
                        Text("Confirm password")
                            .font(.subheadline)
                            .fontWeight(.medium)
                        SecureField("Confirm your password", text: $viewModel.confirmPassword)
                            .textFieldStyle(.roundedBorder)
                            .textContentType(.newPassword)
                            .accessibilityIdentifier("confirmPasswordField")
                    }

                    if let error = viewModel.errorMessage {
                        Text(error)
                            .foregroundStyle(.red)
                            .font(.caption)
                            .multilineTextAlignment(.center)
                            .accessibilityIdentifier("registerErrorMessage")
                    }

                    Button {
                        Task {
                            await viewModel.register()
                        }
                    } label: {
                        if viewModel.isLoading {
                            ProgressView()
                                .progressViewStyle(.circular)
                                .tint(.white)
                        } else {
                            Text("Sign up")
                        }
                    }
                    .frame(maxWidth: .infinity, minHeight: 44)
                    .background(Color.accentColor)
                    .foregroundColor(.white)
                    .fontWeight(.medium)
                    .clipShape(RoundedRectangle(cornerRadius: 2))
                    .disabled(viewModel.isLoading)
                    .accessibilityIdentifier("registerButton")
                }

                Spacer()
            }
            .padding()
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") {
                        dismiss()
                    }
                }
            }
            .onChange(of: viewModel.registrationComplete) { _, complete in
                if complete {
                    dismiss()
                }
            }
        }
    }
}

#Preview {
    RegisterView()
}
