//
//  CalendarSettingsService.swift
//  Selko
//

import Foundation
import Supabase

struct UserCalendarSettings: Codable, Sendable {
    let userId: UUID
    let targetCalendarId: String?
    let defaultInvitees: String?
    let updatedAt: Date?

    enum CodingKeys: String, CodingKey {
        case userId = "user_id"
        case targetCalendarId = "target_calendar_id"
        case defaultInvitees = "default_invitees"
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
}
