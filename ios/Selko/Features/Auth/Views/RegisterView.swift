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
            VStack(spacing: 24) {
                Spacer()

                Text("Create Account")
                    .font(.largeTitle)
                    .fontWeight(.bold)

                VStack(spacing: 16) {
                    TextField("Email", text: $viewModel.email)
                        .textFieldStyle(.roundedBorder)
                        .textContentType(.emailAddress)
                        .keyboardType(.emailAddress)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                        .accessibilityIdentifier("registerEmailField")

                    SecureField("Password", text: $viewModel.password)
                        .textFieldStyle(.roundedBorder)
                        .textContentType(.newPassword)
                        .accessibilityIdentifier("registerPasswordField")

                    SecureField("Confirm Password", text: $viewModel.confirmPassword)
                        .textFieldStyle(.roundedBorder)
                        .textContentType(.newPassword)
                        .accessibilityIdentifier("confirmPasswordField")

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
                            Text("Create Account")
                        }
                    }
                    .buttonStyle(.borderedProminent)
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
