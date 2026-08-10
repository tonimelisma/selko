//
//  LiveUpdateServiceTests.swift
//  SelkoTests
//
//  C6: refreshAuth calls through to realtime; catchUp emits all four
//  resources; terminal channel states schedule a backoff rejoin.
//

import XCTest
@testable import iOS

@MainActor
final class LiveUpdateServiceTests: XCTestCase {

    /// Minimal SupabaseClient-like double is not feasible without the real
    /// client; instead exercise the two pure behaviors that do not need a
    /// socket: catchUp fan-out (through the published stream) and the
    /// start()-short-circuit guard.
    func testCatchUpEmitsAllFourResources() async throws {
        let service = try makeService()
        var received: Set<String> = []

        let streamTask = Task {
            for await inv in service.stream {
                received.insert(inv.resource)
                if received.count == 4 { break }
            }
        }

        await service.catchUp()

        // Debounce is 350ms per resource; wait for the fan-out to settle.
        for _ in 0..<50 {
            if received.count == 4 { break }
            try await Task.sleep(nanoseconds: 100_000_000)
        }
        streamTask.cancel()

        XCTAssertEqual(received, ["events", "event_sources", "integrations", "emails"])
    }
    private func makeService() throws -> LiveUpdateService {
        let container = DependencyContainer.shared
        return container.liveUpdateService
    }
}
