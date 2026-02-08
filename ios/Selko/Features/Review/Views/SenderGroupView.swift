//
//  SenderGroupView.swift
//  Selko
//

import SwiftUI

struct SenderGroupView: View {
    let group: SenderGroup
    let onApproveAll: () -> Void

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(group.senderName)
                    .font(.subheadline)
                    .fontWeight(.semibold)
                    .foregroundStyle(.primary)

                if group.senderName != group.senderEmail {
                    Text(group.senderEmail)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }

            Spacer()

            if group.events.count > 1 {
                Button {
                    onApproveAll()
                } label: {
                    Text("Approve All (\(group.events.count))")
                        .font(.caption)
                        .fontWeight(.medium)
                }
                .buttonStyle(.bordered)
                .controlSize(.mini)
                .tint(.green)
            }
        }
        .textCase(nil)
    }
}
