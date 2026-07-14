import SwiftUI

struct LoginView: View {
    @State private var viewModel = LoginViewModel()
    @State private var showRegister = false

    var body: some View {
        ZStack {
            Color.selkoPaper.ignoresSafeArea()
            VStack(spacing: 20) {
                Spacer()
                SelkoLogoMark(size: 56)
                Text("Selko")
                    .font(SelkoTypography.display)
                    .foregroundStyle(Color.selkoInk)
                Text("Sign in to continue.")
                    .font(SelkoTypography.body)
                    .foregroundStyle(Color.selkoMuted)

                VStack(alignment: .leading, spacing: 16) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Email")
                            .font(SelkoTypography.title)
                            .foregroundStyle(Color.selkoInk)
                        TextField("you@example.com", text: $viewModel.email)
                            .textContentType(.emailAddress)
                            .keyboardType(.emailAddress)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .padding(.horizontal, 14)
                            .frame(height: 46)
                            .background(Color.selkoPaper)
                            .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).stroke(Color.selkoBorder, lineWidth: 1.5))
                            .accessibilityLabel("Email address")
                            .accessibilityIdentifier("emailField")
                    }

                    VStack(alignment: .leading, spacing: 6) {
                        Text("Password")
                            .font(SelkoTypography.title)
                            .foregroundStyle(Color.selkoInk)
                        SecureField("Your password", text: $viewModel.password)
                            .textContentType(.password)
                            .padding(.horizontal, 14)
                            .frame(height: 46)
                            .background(Color.selkoPaper)
                            .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).stroke(Color.selkoBorder, lineWidth: 1.5))
                            .accessibilityLabel("Password")
                            .accessibilityIdentifier("passwordField")
                    }

                    if let error = viewModel.errorMessage {
                        Text(error)
                            .foregroundStyle(Color.selkoRust)
                            .font(SelkoTypography.caption)
                            .multilineTextAlignment(.center)
                            .frame(maxWidth: .infinity)
                            .accessibilityIdentifier("errorMessage")
                    }

                    Button {
                        Task { await viewModel.login() }
                    } label: {
                        Group {
                            if viewModel.isLoading {
                                ProgressView().tint(Color.selkoOnPrimary)
                            } else {
                                Text("Sign in")
                            }
                        }
                        .frame(maxWidth: .infinity, minHeight: 46)
                    }
                    .background(Color.accentColor)
                    .foregroundStyle(Color.selkoOnPrimary)
                    .font(SelkoTypography.title)
                    .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                    .shadow(color: Color.accentColor.opacity(0.35), radius: 10, y: 5)
                    .disabled(viewModel.isLoading)
                    .accessibilityIdentifier("signInButton")
                }
                .padding(20)
                .frame(maxWidth: 420)
                .selkoCard()

                HStack(spacing: 4) {
                    Text("Don't have an account?")
                        .font(SelkoTypography.caption)
                    Button("Sign up") { showRegister = true }
                        .font(SelkoTypography.caption.weight(.bold))
                        .foregroundStyle(Color.selkoRust)
                        .frame(minWidth: 44, minHeight: 44)
                        .accessibilityIdentifier("createAccountButton")
                }
                Spacer()
            }
            .padding()
        }
        .fullScreenCover(isPresented: $showRegister) { RegisterView() }
    }
}

#Preview { LoginView() }
