//
//  CalendarSettingsService.swift
//  Selko
//

import Foundation
import Supabase

struct UserCalendarSettings: Codable, Sendable {
    let id: UUID
    let userId: UUID
    let defaultCalendarId: String?
    let defaultCalendarName: String?
    let createdAt: Date?
    let updatedAt: Date?

    enum CodingKeys: String, CodingKey {
        case id
        case userId = "user_id"
        case defaultCalendarId = "default_calendar_id"
        case defaultCalendarName = "default_calendar_name"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

protocol CalendarSettingsServiceProtocol: Sendable {
    func getSettings() async throws -> UserCalendarSettings?
    func updateDefaultCalendar(calendarId: String, calendarName: String) async throws -> UserCalendarSettings
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
                    "default_calendar_id": calendarId,
                    "default_calendar_name": calendarName
                ])
                .eq("id", value: existing.id)
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
                    "default_calendar_id": calendarId,
                    "default_calendar_name": calendarName
                ])
                .select()
                .single()
                .execute()
                .value
            return created
        }
    }
}
