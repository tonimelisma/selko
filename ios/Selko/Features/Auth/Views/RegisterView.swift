//
//  RegisterView.swift
//  Selko
//
//  Created by Claude on 1/26/26.
//

import SwiftUI
import UIKit

/// A TextField wrapper that correctly renders placeholder text in grey.
/// SwiftUI's TextField ignores foreground styling on placeholder text,
/// always rendering it in the accent/tint color. UITextField is the only
/// way to control placeholder color on iOS.
private struct PlaceholderTextField: UIViewRepresentable {
    let placeholder: String
    @Binding var text: String
    var textContentType: UITextContentType?
    var keyboardType: UIKeyboardType = .default
    var accessibilityIdentifier: String?

    func makeUIView(context: Context) -> UITextField {
        let field = UITextField()
        field.attributedPlaceholder = NSAttributedString(
            string: placeholder,
            attributes: [.foregroundColor: UIColor.placeholderText]
        )
        field.font = .preferredFont(forTextStyle: .body)
        field.borderStyle = .roundedRect
        field.textContentType = textContentType
        field.keyboardType = keyboardType
        field.autocorrectionType = .no
        field.autocapitalizationType = .none
        field.accessibilityLabel = String(localized: "Email address")
        field.accessibilityIdentifier = accessibilityIdentifier
        field.delegate = context.coordinator
        field.setContentHuggingPriority(.defaultHigh, for: .vertical)
        return field
    }

    func updateUIView(_ uiView: UITextField, context: Context) {
        if uiView.text != text {
            uiView.text = text
        }
    }

    func makeCoordinator() -> Coordinator {
        Coordinator(text: $text)
    }

    class Coordinator: NSObject, UITextFieldDelegate {
        var text: Binding<String>

        init(text: Binding<String>) {
            self.text = text
        }

        func textFieldDidChangeSelection(_ textField: UITextField) {
            text.wrappedValue = textField.text ?? ""
        }
    }
}

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
                        PlaceholderTextField(
                            placeholder: "you@example.com",
                            text: $viewModel.email,
                            textContentType: .emailAddress,
                            keyboardType: .emailAddress,
                            accessibilityIdentifier: "registerEmailField"
                        )
                        .frame(height: 36)
                    }

                    VStack(alignment: .leading, spacing: 4) {
                        Text("Password")
                            .font(.subheadline)
                            .fontWeight(.medium)
                        SecureField("Choose a password", text: $viewModel.password)
                            .textFieldStyle(.roundedBorder)
                            .textContentType(.newPassword)
                            .accessibilityLabel("Password")
                            .accessibilityIdentifier("registerPasswordField")
                    }

                    VStack(alignment: .leading, spacing: 4) {
                        Text("Confirm password")
                            .font(.subheadline)
                            .fontWeight(.medium)
                        SecureField("Confirm your password", text: $viewModel.confirmPassword)
                            .textFieldStyle(.roundedBorder)
                            .textContentType(.newPassword)
                            .accessibilityLabel("Confirm password")
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
                    .accessibilityHint("Creates your account")
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
