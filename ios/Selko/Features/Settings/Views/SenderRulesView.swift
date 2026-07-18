//
//  SenderRulesView.swift
//  Selko
//

import SwiftUI

struct SenderRulesView: View {
    @State private var rules: [SenderRule] = []
    @State private var isLoading = false
    @State private var errorMessage: String?
    @State private var newRuleText = ""
    @State private var newRuleAction: SenderRuleAction = .ignore
    @State private var showDeleteConfirmation = false
    @State private var ruleToDelete: SenderRule?

    private let senderRuleService: SenderRuleServiceProtocol

    private var approvedRules: [SenderRule] { rules.filter { $0.ruleAction == .autoApprove } }
    private var ignoredRules: [SenderRule] { rules.filter { $0.ruleAction == .ignore } }

    init(senderRuleService: SenderRuleServiceProtocol? = nil) {
        self.senderRuleService = senderRuleService ?? DependencyContainer.shared.senderRuleService
    }

    var body: some View {
        List {
            Section("Auto-approved") {
                if isLoading {
                    HStack {
                        ProgressView()
                            .controlSize(.small)
                        Text("Loading rules...")
                            .foregroundStyle(Color.selkoMuted)
                    }
                } else if rules.isEmpty {
                    Text("No sender rules yet. Add a rule to automatically approve or ignore emails from specific senders or domains.")
                        .foregroundStyle(Color.selkoMuted)
                        .font(SelkoTypography.body)
                } else {
                    ForEach(approvedRules) { rule in
                        ruleRow(rule)
                    }
                }
            }

            if !ignoredRules.isEmpty {
                Section("Ignored") {
                    ForEach(ignoredRules) { rule in ruleRow(rule) }
                }
            }

            Section("Add Rule") {
                HStack {
                    TextField("email@example.com or domain.com", text: $newRuleText)
                        .textContentType(.emailAddress)
                        .autocapitalization(.none)
                        .disableAutocorrection(true)
                        .accessibilityIdentifier("newRuleTextField")

                    Picker("Action", selection: $newRuleAction) {
                        Text("Ignore").tag(SenderRuleAction.ignore)
                        Text("Auto-approve").tag(SenderRuleAction.autoApprove)
                    }
                    .labelsHidden()
                    .accessibilityIdentifier("newRuleActionPicker")
                }

                Button {
                    Task { await addRule() }
                } label: {
                    HStack {
                        Spacer()
                        Label("Add Rule", systemImage: "plus.circle")
                        Spacer()
                    }
                }
                .buttonStyle(.selko(.primary))
                .disabled(newRuleText.trimmingCharacters(in: .whitespaces).isEmpty)
                .accessibilityIdentifier("addRuleButton")
            }
        }
        .scrollContentBackground(.hidden)
        .background(Color.selkoPaper)
        .navigationTitle("Sender Rules")
        .task {
            await loadRules()
        }
        .refreshable {
            await loadRules()
        }
        .confirmationDialog(
            "Delete Rule",
            isPresented: $showDeleteConfirmation,
            presenting: ruleToDelete
        ) { rule in
            Button("Delete", role: .destructive) {
                Task { await deleteRule(rule) }
            }
            Button("Cancel", role: .cancel) {
                ruleToDelete = nil
            }
        } message: { rule in
            Text("Are you sure you want to delete the rule for \(rule.displayTarget)?")
        }
        .alert("Error", isPresented: .constant(errorMessage != nil)) {
            Button("OK") {
                errorMessage = nil
            }
        } message: {
            if let error = errorMessage {
                Text(error)
            }
        }
    }

    // MARK: - Rule Row

    @ViewBuilder
    private func ruleRow(_ rule: SenderRule) -> some View {
        HStack(spacing: 12) {
            SelkoStatusIndicator(
                text: rule.ruleAction == .ignore ? "Ignore" : "Auto-approve",
                systemImage: rule.ruleAction == .ignore ? "nosign" : "checkmark.circle",
                tone: rule.ruleAction == .ignore ? .error : .success
            )

            VStack(alignment: .leading, spacing: 2) {
                Text(rule.displayTarget)
                    .font(SelkoTypography.title)
                    .foregroundStyle(Color.selkoInk)
            }

            Spacer()
            Button(role: .destructive) {
                ruleToDelete = rule
                showDeleteConfirmation = true
            } label: {
                Image(systemName: "trash")
                    .frame(width: 20, height: 20)
            }
            .buttonStyle(.selko(.tertiary))
            .foregroundStyle(Color.selkoError)
            .accessibilityLabel("Delete rule for \(rule.displayTarget)")
        }
    }

    // MARK: - Actions

    private func loadRules() async {
        isLoading = true
        errorMessage = nil

        do {
            rules = try await senderRuleService.fetchRules()
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }

    private func addRule() async {
        let trimmed = newRuleText.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty else { return }

        let isEmail = trimmed.contains("@")
        let senderEmail = isEmail ? trimmed : nil
        let senderDomain = isEmail ? nil : trimmed

        do {
            let rule = try await senderRuleService.createRule(
                senderEmail: senderEmail,
                senderDomain: senderDomain,
                action: newRuleAction
            )
            rules.insert(rule, at: 0)
            newRuleText = ""
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func deleteRule(_ rule: SenderRule) async {
        do {
            try await senderRuleService.deleteRule(id: rule.id)
            rules.removeAll { $0.id == rule.id }
        } catch {
            errorMessage = error.localizedDescription
        }
        ruleToDelete = nil
    }
}

#Preview {
    NavigationStack {
        SenderRulesView()
    }
}
