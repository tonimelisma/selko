//
//  MockCalendarSettingsService.swift
//  SelkoTests
//

import Foundation
@testable import iOS

final class MockCalendarSettingsService: CalendarSettingsServiceProtocol, @unchecked Sendable {
    var getSettingsResult: Result<UserCalendarSettings?, Error> = .success(nil)
    var updateDefaultCalendarResult: Result<UserCalendarSettings, Error> = .success(
        UserCalendarSettings(userId: UUID(), targetCalendarId: "cal_1", defaultInvitees: nil, updatedAt: Date())
    )

    var getSettingsCallCount = 0
    var updateDefaultCalendarCallCount = 0
    var lastUpdateCalendarId: String?
    var lastUpdateCalendarName: String?

    func getSettings() async throws -> UserCalendarSettings? {
        getSettingsCallCount += 1
        switch getSettingsResult {
        case .success(let settings): return settings
        case .failure(let error): throw error
        }
    }

    func updateDefaultCalendar(calendarId: String, calendarName: String) async throws -> UserCalendarSettings {
        updateDefaultCalendarCallCount += 1
        lastUpdateCalendarId = calendarId
        lastUpdateCalendarName = calendarName
        switch updateDefaultCalendarResult {
        case .success(let settings): return settings
        case .failure(let error): throw error
        }
    }
}
