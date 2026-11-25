import SwiftUI

struct RegisterView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var viewModel = RegisterViewModel()

    var body: some View {
        NavigationStack {
            ZStack {
                Color.selkoPaper.ignoresSafeArea()
                VStack(spacing: 20) {
                    SelkoLogoMark(size: 52)
                    Text("Create your account")
                        .font(SelkoTypography.sectionTitle)
                        .foregroundStyle(Color.selkoInk)

                    VStack(alignment: .leading, spacing: 16) {
                        authField("Email", placeholder: "you@example.com", text: $viewModel.email, identifier: "registerEmailField")
                        authSecureField("Password", placeholder: "Choose a password", text: $viewModel.password, identifier: "registerPasswordField")
                        authSecureField("Confirm password", placeholder: "Confirm your password", text: $viewModel.confirmPassword, identifier: "confirmPasswordField")

                        if let error = viewModel.errorMessage {
                            Text(error)
                                .foregroundStyle(Color.selkoError)
                                .font(SelkoTypography.caption)
                                .multilineTextAlignment(.center)
                                .frame(maxWidth: .infinity)
                                .accessibilityIdentifier("registerErrorMessage")
                        }

                        Button {
                            Task { await viewModel.register() }
                        } label: {
                            Group {
                                if viewModel.isLoading { ProgressView().tint(Color.selkoOnPrimary) } else { Text("Sign up") }
                            }
                            .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.selko(.primary))
                        .disabled(viewModel.isLoading)
                        .accessibilityIdentifier("registerButton")
                    }
                    .padding(20)
                    .frame(maxWidth: 420)
                    .selkoCard()
                    Spacer()
                }
                .padding()
            }
            .navigationTitle("Sign up")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
            }
            .onChange(of: viewModel.registrationComplete) { _, complete in if complete { dismiss() } }
        }
    }

    @ViewBuilder
    private func authField(_ label: String, placeholder: String, text: Binding<String>, identifier: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(label).font(SelkoTypography.title).foregroundStyle(Color.selkoInk)
            TextField(placeholder, text: text)
            .textContentType(.emailAddress)
                .keyboardType(.emailAddress)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .selkoInput()
                .accessibilityLabel(label)
                .accessibilityIdentifier(identifier)
        }
    }

    @ViewBuilder
    private func authSecureField(_ label: String, placeholder: String, text: Binding<String>, identifier: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(label).font(SelkoTypography.title).foregroundStyle(Color.selkoInk)
            SecureField(placeholder, text: text)
            .textContentType(.newPassword)
                .selkoInput()
                .accessibilityLabel(label)
                .accessibilityIdentifier(identifier)
        }
    }
}

#Preview { RegisterView() }
