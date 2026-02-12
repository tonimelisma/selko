//
//  EmailGroupView.swift
//  Selko
//

import SwiftUI

struct EmailGroupView: View {
    let emailGroup: EmailGroup
    let onApproveAll: () -> Void

    var body: some View {
        HStack {
            Image(systemName: "envelope")
                .font(.caption)
                .foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 1) {
                Text(emailGroup.subject)
                    .font(.subheadline)
                    .fontWeight(.medium)
                if let date = emailGroup.dateSent {
                    Text(date, style: .date)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
            Spacer()
            if emailGroup.events.count > 1 {
                Button {
                    onApproveAll()
                } label: {
                    Text("Approve All (\(emailGroup.events.count))")
                        .font(.caption)
                        .fontWeight(.medium)
                }
                .buttonStyle(.bordered)
                .tint(.accentColor)
            }
        }
        .textCase(nil)
    }
}
