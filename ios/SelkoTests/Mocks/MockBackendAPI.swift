//
//  MockBackendAPI.swift
//  SelkoTests
//

import Foundation
@testable import iOS

final class MockBackendAPI: BackendAPIProtocol, @unchecked Sendable {
    var listCalendarsResult: Result<[CalendarInfo], Error> = .success([])

    var listCalendarsCallCount = 0
    var undoHistoryEventCallCount = 0
    var lastUndoHistoryEventId: UUID?
    var lastUndoHistoryForce: Bool = false
    var undoHistoryEventResult: Result<EventChangeResponse, Error> = .success(
        EventChangeResponse(eventId: UUID().uuidString, status: "pending_review")
    )

    func syncEmails(maxResults: Int, fetchAttachments: Bool) async throws -> EmailSyncResponse {
        return EmailSyncResponse(fetched: 0, saved: 0, attachmentsDownloaded: nil)
    }

    func processEmail(emailId: UUID) async throws -> EmailProcessResponse {
        return EmailProcessResponse(numEvents: 0, numNew: 0, numUpdated: 0, eventIds: [])
    }

    func batchProcessEmails(maxEmails: Int) async throws -> EmailProcessResponse {
        return EmailProcessResponse(numEvents: 0, numNew: 0, numUpdated: 0, eventIds: [])
    }

    func listCalendars() async throws -> [CalendarInfo] {
        listCalendarsCallCount += 1
        switch listCalendarsResult {
        case .success(let calendars): return calendars
        case .failure(let error): throw error
        }
    }

    func syncEventToCalendar(eventId: UUID) async throws -> CalendarSyncResponse {
        return CalendarSyncResponse(eventId: eventId.uuidString, googleCalendarEventId: "gcal_123", syncedAt: "2026-01-01T00:00:00Z", status: "synced")
    }

    func applyEventChange(eventId: UUID) async throws -> EventChangeResponse {
        return EventChangeResponse(eventId: eventId.uuidString, status: "approved")
    }

    func rejectEventChange(eventId: UUID) async throws -> EventChangeResponse {
        return EventChangeResponse(eventId: eventId.uuidString, status: "synced")
    }

    func undoHistoryEvent(eventId: UUID, force: Bool) async throws -> EventChangeResponse {
        undoHistoryEventCallCount += 1
        lastUndoHistoryEventId = eventId
        lastUndoHistoryForce = force
        switch undoHistoryEventResult {
        case .success(let response): return response
        case .failure(let error): throw error
        }
    }

    func getGmailAuthUrl(redirectUri: String?) -> String {
        return "https://example.com/auth"
    }

    func getOutlookAuthUrl(redirectUri: String?) -> String {
        return "https://example.com/outlook-auth"
    }

    func getCalendarAuthUrl(redirectUri: String?) -> String {
        return "https://example.com/calendar-auth"
    }

    func getPhotosAuthUrl(redirectUri: String?) -> String {
        return "https://example.com/photos-auth"
    }

    func checkHealth() async throws -> HealthResponse {
        return HealthResponse(status: "ok")
    }
}
