//
//  CalendarSettingsService.swift
//  Selko
//

import Foundation
import Supabase

enum AllDayDisplayMode: String, Codable, CaseIterable, Sendable {
    case allDay = "all_day"
    case day9to5 = "day_9_to_5"
    case morning8to9 = "morning_8_to_9"
    case custom = "custom"

    var displayName: String {
        switch self {
        case .allDay: return String(localized: "settings.date_only_all_day")
        case .day9to5: return String(localized: "settings.date_only_day_9_to_5")
        case .morning8to9: return String(localized: "settings.date_only_morning_8_to_9")
        case .custom: return String(localized: "settings.date_only_custom")
        }
    }
}

struct UserCalendarSettings: Codable, Sendable {
    let userId: UUID
    let targetCalendarId: String?
    let defaultInvitees: String?
    let allDayDisplayMode: AllDayDisplayMode?
    let allDayCustomStart: String?
    let allDayCustomEnd: String?
    let updatedAt: Date?

    enum CodingKeys: String, CodingKey {
        case userId = "user_id"
        case targetCalendarId = "target_calendar_id"
        case defaultInvitees = "default_invitees"
        case allDayDisplayMode = "all_day_display_mode"
        case allDayCustomStart = "all_day_custom_start"
        case allDayCustomEnd = "all_day_custom_end"
        case updatedAt = "updated_at"
    }
}

protocol CalendarSettingsServiceProtocol: Sendable {
    func getSettings() async throws -> UserCalendarSettings?
    func updateDefaultCalendar(calendarId: String, calendarName: String) async throws -> UserCalendarSettings
    func updateAllDayDisplayPreference(
        mode: AllDayDisplayMode,
        customStart: String?,
        customEnd: String?
    ) async throws -> UserCalendarSettings
}

final class CalendarSettingsService: CalendarSettingsServiceProtocol, @unchecked Sendable {
    private let supabase: SupabaseClient

    init(supabase: SupabaseClient) {
        self.supabase = supabase
    }

    func getSettings() async throws -> UserCalendarSettings? {
        let settings: [UserCalendarSettings] = try await supabase.from("user_calendar_settings")
            .select()
            .execute()
            .value

        return settings.first
    }

    func updateDefaultCalendar(calendarId: String, calendarName: String) async throws -> UserCalendarSettings {
        // Try to get existing settings first
        if let existing = try await getSettings() {
            let updated: UserCalendarSettings = try await supabase.from("user_calendar_settings")
                .update([
                    "target_calendar_id": calendarId
                ])
                .eq("user_id", value: existing.userId)
                .select()
                .single()
                .execute()
                .value
            return updated
        } else {
            // Get current user ID
            guard let session = try? await supabase.auth.session else {
                throw BackendAPIError.notAuthenticated
            }
            let created: UserCalendarSettings = try await supabase.from("user_calendar_settings")
                .insert([
                    "user_id": session.user.id.uuidString,
                    "target_calendar_id": calendarId
                ])
                .select()
                .single()
                .execute()
                .value
            return created
        }
    }

    func updateAllDayDisplayPreference(
        mode: AllDayDisplayMode,
        customStart: String?,
        customEnd: String?
    ) async throws -> UserCalendarSettings {
        var payload: [String: AnyJSON] = [
            "all_day_display_mode": .string(mode.rawValue)
        ]
        // Only write custom times in custom mode so preset switches preserve them.
        if mode == .custom {
            if let customStart {
                payload["all_day_custom_start"] = .string(customStart)
            }
            if let customEnd {
                payload["all_day_custom_end"] = .string(customEnd)
            }
        }

        if let existing = try await getSettings() {
            let updated: UserCalendarSettings = try await supabase.from("user_calendar_settings")
                .update(payload)
                .eq("user_id", value: existing.userId)
                .select()
                .single()
                .execute()
                .value
            return updated
        }

        guard let session = try? await supabase.auth.session else {
            throw BackendAPIError.notAuthenticated
        }
        payload["user_id"] = .string(session.user.id.uuidString)
        let created: UserCalendarSettings = try await supabase.from("user_calendar_settings")
            .insert(payload)
            .select()
            .single()
            .execute()
            .value
        return created
    }
}
