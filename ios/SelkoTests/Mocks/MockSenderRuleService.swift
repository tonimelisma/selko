//
//  MockSenderRuleService.swift
//  SelkoTests
//

import Foundation
@testable import iOS

final class MockSenderRuleService: SenderRuleServiceProtocol, @unchecked Sendable {
    var fetchRulesResult: Result<[SenderRule], Error> = .success([])
    var createRuleResult: Result<SenderRule, Error> = .success(SenderRule.mock)
    var deleteRuleError: Error?

    var fetchRulesCallCount = 0
    var createRuleCallCount = 0
    var deleteRuleCallCount = 0
    var lastCreateEmail: String?
    var lastCreateDomain: String?
    var lastCreateAction: SenderRuleAction?
    var lastDeleteId: UUID?

    func fetchRules() async throws -> [SenderRule] {
        fetchRulesCallCount += 1
        switch fetchRulesResult {
        case .success(let rules):
            return rules
        case .failure(let error):
            throw error
        }
    }

    func createRule(senderEmail: String?, senderDomain: String?, action: SenderRuleAction) async throws -> SenderRule {
        createRuleCallCount += 1
        lastCreateEmail = senderEmail
        lastCreateDomain = senderDomain
        lastCreateAction = action
        switch createRuleResult {
        case .success(let rule):
            return rule
        case .failure(let error):
            throw error
        }
    }

    func deleteRule(id: UUID) async throws {
        deleteRuleCallCount += 1
        lastDeleteId = id
        if let error = deleteRuleError {
            throw error
        }
    }
}
