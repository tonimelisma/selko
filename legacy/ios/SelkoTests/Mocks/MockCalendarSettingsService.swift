//
//  MockCalendarSettingsService.swift
//  SelkoTests
//

import Foundation
@testable import iOS

final class MockCalendarSettingsService: CalendarSettingsServiceProtocol, @unchecked Sendable {
    var getSettingsResult: Result<UserCalendarSettings?, Error> = .success(nil)
    var updateDefaultCalendarResult: Result<UserCalendarSettings, Error> = .success(
        UserCalendarSettings(
            userId: UUID(),
            targetCalendarId: "cal_1",
            defaultInvitees: nil,
            allDayDisplayMode: .allDay,
            allDayCustomStart: nil,
            allDayCustomEnd: nil,
            updatedAt: Date()
        )
    )
    var updateAllDayDisplayPreferenceResult: Result<UserCalendarSettings, Error> = .success(
        UserCalendarSettings(
            userId: UUID(),
            targetCalendarId: "cal_1",
            defaultInvitees: nil,
            allDayDisplayMode: .day9to5,
            allDayCustomStart: nil,
            allDayCustomEnd: nil,
            updatedAt: Date()
        )
    )

    var getSettingsCallCount = 0
    var updateDefaultCalendarCallCount = 0
    var updateAllDayDisplayPreferenceCallCount = 0
    var lastUpdateCalendarId: String?
    var lastUpdateCalendarName: String?
    var lastAllDayMode: AllDayDisplayMode?
    var lastCustomStart: String?
    var lastCustomEnd: String?

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

    func updateAllDayDisplayPreference(
        mode: AllDayDisplayMode,
        customStart: String?,
        customEnd: String?
    ) async throws -> UserCalendarSettings {
        updateAllDayDisplayPreferenceCallCount += 1
        lastAllDayMode = mode
        lastCustomStart = customStart
        lastCustomEnd = customEnd
        switch updateAllDayDisplayPreferenceResult {
        case .success(let settings): return settings
        case .failure(let error): throw error
        }
    }
}
