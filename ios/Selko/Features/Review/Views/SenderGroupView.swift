//
//  SenderGroupView.swift
//  Selko
//

import SwiftUI

struct SenderGroupView: View {
    let group: SenderGroup
    let onApproveAll: () -> Void
    let onRejectAll: () -> Void
    let onIgnoreSender: () -> Void
    let onAutoApproveSender: () -> Void

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

            Menu {
                if group.events.count > 1 {
                    Button {
                        onApproveAll()
                    } label: {
                        Label("Approve all", systemImage: "checkmark")
                    }

                    Button(role: .destructive) {
                        onRejectAll()
                    } label: {
                        Label("Reject all", systemImage: "xmark")
                    }

                    Divider()
                }

                Button {
                    onAutoApproveSender()
                } label: {
                    Label("Auto-approve sender", systemImage: "checkmark.circle")
                }

                Button(role: .destructive) {
                    onIgnoreSender()
                } label: {
                    Label("Ignore sender", systemImage: "nosign")
                }
            } label: {
                Image(systemName: "ellipsis.circle")
                    .font(.title3)
                    .foregroundStyle(.secondary)
            }
            .accessibilityLabel("Actions for this sender")
        }
        .textCase(nil)
    }
}
