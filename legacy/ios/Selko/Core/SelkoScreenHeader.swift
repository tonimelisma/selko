import SwiftUI

struct SelkoScreenHeader: View {
    let title: String
    let subtitle: String
    let email: String

    private var initials: String {
        let localPart = email.split(separator: "@").first.map(String.init) ?? "SK"
        let letters = localPart.filter(\.isLetter)
        return String((letters.isEmpty ? localPart : letters).prefix(2)).uppercased()
    }

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(SelkoTypography.screenTitle)
                    .foregroundStyle(Color.selkoInk)
                Text(subtitle)
                    .font(SelkoTypography.caption)
                    .foregroundStyle(Color.selkoMuted)
            }
            Spacer(minLength: 8)
            Text(initials)
                .font(SelkoTypography.caption.weight(.bold))
                .foregroundStyle(Color.selkoOnPrimary)
                .frame(width: 40, height: 40)
                .background(Color.accentColor)
                .clipShape(Circle())
                .accessibilityLabel(email.isEmpty ? "Account" : email)
        }
        .padding(.horizontal, 16)
        .padding(.top, 12)
        .padding(.bottom, 10)
    }
}
