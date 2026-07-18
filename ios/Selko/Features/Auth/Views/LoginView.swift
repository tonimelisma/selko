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
                            .selkoInput()
                            .accessibilityLabel("Email address")
                            .accessibilityIdentifier("emailField")
                    }

                    VStack(alignment: .leading, spacing: 6) {
                        Text("Password")
                            .font(SelkoTypography.title)
                            .foregroundStyle(Color.selkoInk)
                        SecureField("Your password", text: $viewModel.password)
                            .textContentType(.password)
                            .selkoInput()
                            .accessibilityLabel("Password")
                            .accessibilityIdentifier("passwordField")
                    }

                    if let error = viewModel.errorMessage {
                        Text(error)
                            .foregroundStyle(Color.selkoError)
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
                        .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.selko(.primary))
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
                        .buttonStyle(.selko(.tertiary))
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
