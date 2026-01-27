//
//  MockKeychainManager.swift
//  SelkoTests
//
//  Created by Claude on 1/26/26.
//

import Foundation
@testable import iOS

final class MockKeychainManager: KeychainManagerProtocol, @unchecked Sendable {
    var storage: [String: Data] = [:]
    var saveError: Error?
    var loadError: Error?
    var deleteError: Error?

    var saveCallCount = 0
    var loadCallCount = 0
    var deleteCallCount = 0

    func save(_ data: Data, forKey key: String) throws {
        saveCallCount += 1
        if let error = saveError {
            throw error
        }
        storage[key] = data
    }

    func load(forKey key: String) throws -> Data? {
        loadCallCount += 1
        if let error = loadError {
            throw error
        }
        return storage[key]
    }

    func delete(forKey key: String) throws {
        deleteCallCount += 1
        if let error = deleteError {
            throw error
        }
        storage.removeValue(forKey: key)
    }
}
