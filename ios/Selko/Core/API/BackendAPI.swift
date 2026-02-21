//
//  BackendAPI.swift
//  Selko
//
//  Backend API client for server-side operations that require secrets.
//  Use this for: OAuth flows, email sync, LLM processing, calendar sync.
//

import Foundation
import Supabase

enum BackendAPIError: Error, LocalizedError {
    case notAuthenticated
    case invalidResponse
    case serverError(String)
    case networkError(Error)

    var errorDescription: String? {
        switch self {
        case .notAuthenticated:
            return "Not authenticated"
        case .invalidResponse:
            return "Invalid server response"
        case .serverError(let message):
            return message
        case .networkError(let error):
            return error.localizedDescription
        }
    }
}

// MARK: - Response Types

struct EmailSyncResponse: Codable {
    let fetched: Int
    let saved: Int
    let attachmentsDownloaded: Int?

    enum CodingKeys: String, CodingKey {
        case fetched
        case saved
        case attachmentsDownloaded = "attachments_downloaded"
    }
}

struct EmailProcessResponse: Codable {
    let numEvents: Int
    let numNew: Int
    let numUpdated: Int
    let eventIds: [String]

    enum CodingKeys: String, CodingKey {
        case numEvents = "num_events"
        case numNew = "num_new"
        case numUpdated = "num_updated"
        case eventIds = "event_ids"
    }
}

struct CalendarInfo: Codable, Identifiable {
    let id: String
    let name: String
    let isPrimary: Bool
    let isSelected: Bool

    enum CodingKeys: String, CodingKey {
        case id
        case name
        case isPrimary = "is_primary"
        case isSelected = "is_selected"
    }
}

struct CalendarSyncResponse: Codable {
    let eventId: String
    let googleCalendarEventId: String
    let syncedAt: String
    let status: String

    enum CodingKeys: String, CodingKey {
        case eventId = "event_id"
        case googleCalendarEventId = "google_calendar_event_id"
        case syncedAt = "synced_at"
        case status
    }
}

struct HealthResponse: Codable {
    let status: String
}

private struct APIErrorResponse: Codable {
    let detail: String?
    let message: String?
}

// MARK: - Backend API Protocol

protocol BackendAPIProtocol: Sendable {
    func syncEmails(maxResults: Int, fetchAttachments: Bool) async throws -> EmailSyncResponse
    func processEmail(emailId: UUID) async throws -> EmailProcessResponse
    func batchProcessEmails(maxEmails: Int) async throws -> EmailProcessResponse
    func listCalendars() async throws -> [CalendarInfo]
    func syncEventToCalendar(eventId: UUID) async throws -> CalendarSyncResponse
    func getGmailAuthUrl(redirectUri: String?) -> String
    func getCalendarAuthUrl(redirectUri: String?) -> String
    func getPhotosAuthUrl(redirectUri: String?) -> String
    func checkHealth() async throws -> HealthResponse
}

// MARK: - Backend API Implementation

final class BackendAPI: BackendAPIProtocol, @unchecked Sendable {
    private let supabase: SupabaseClient
    private let baseURL: String
    private let decoder: JSONDecoder
    private let encoder: JSONEncoder

    init(supabase: SupabaseClient, baseURL: String? = nil) {
        self.supabase = supabase
        self.baseURL = baseURL ?? Config.apiURL
        self.decoder = JSONDecoder()
        self.encoder = JSONEncoder()
    }

    private func getAccessToken() async throws -> String {
        guard let session = try? await supabase.auth.session else {
            throw BackendAPIError.notAuthenticated
        }
        return session.accessToken
    }

    private func makeRequest(
        path: String,
        method: String,
        body: Data? = nil
    ) async throws -> Data {
        let token = try await getAccessToken()

        guard let url = URL(string: "\(baseURL)\(path)") else {
            throw BackendAPIError.invalidResponse
        }

        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.httpBody = body

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw BackendAPIError.invalidResponse
        }

        if httpResponse.statusCode >= 400 {
            if let errorResponse = try? decoder.decode(APIErrorResponse.self, from: data) {
                throw BackendAPIError.serverError(errorResponse.detail ?? errorResponse.message ?? "Request failed")
            }
            throw BackendAPIError.serverError("Request failed with status \(httpResponse.statusCode)")
        }

        return data
    }

    // MARK: - Email Operations

    private struct SyncEmailsRequest: Encodable {
        let max_results: Int
        let fetch_attachments: Bool
    }

    func syncEmails(maxResults: Int = 50, fetchAttachments: Bool = true) async throws -> EmailSyncResponse {
        let request = SyncEmailsRequest(max_results: maxResults, fetch_attachments: fetchAttachments)
        let body = try encoder.encode(request)

        let data = try await makeRequest(path: "/emails/sync", method: "POST", body: body)
        return try decoder.decode(EmailSyncResponse.self, from: data)
    }

    func processEmail(emailId: UUID) async throws -> EmailProcessResponse {
        let data = try await makeRequest(path: "/emails/\(emailId)/process", method: "POST")
        return try decoder.decode(EmailProcessResponse.self, from: data)
    }

    private struct BatchProcessRequest: Encodable {
        let max_emails: Int
    }

    func batchProcessEmails(maxEmails: Int = 10) async throws -> EmailProcessResponse {
        let request = BatchProcessRequest(max_emails: maxEmails)
        let body = try encoder.encode(request)
        let data = try await makeRequest(path: "/emails/batch-process", method: "POST", body: body)
        return try decoder.decode(EmailProcessResponse.self, from: data)
    }

    // MARK: - Calendar Operations

    func listCalendars() async throws -> [CalendarInfo] {
        let data = try await makeRequest(path: "/calendars", method: "GET")
        return try decoder.decode([CalendarInfo].self, from: data)
    }

    func syncEventToCalendar(eventId: UUID) async throws -> CalendarSyncResponse {
        let data = try await makeRequest(path: "/events/\(eventId)/sync", method: "POST")
        return try decoder.decode(CalendarSyncResponse.self, from: data)
    }

    // MARK: - OAuth

    func getGmailAuthUrl(redirectUri: String? = nil) -> String {
        var urlString = "\(baseURL)/integrations/gmail/auth"
        if let redirectUri = redirectUri {
            guard let encodedRedirect = redirectUri.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) else {
                return urlString
            }
            urlString += "?redirect_uri=\(encodedRedirect)"
        }
        return urlString
    }

    func getCalendarAuthUrl(redirectUri: String? = nil) -> String {
        var urlString = "\(baseURL)/integrations/calendar/auth"
        if let redirectUri = redirectUri {
            guard let encodedRedirect = redirectUri.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) else {
                return urlString
            }
            urlString += "?redirect_uri=\(encodedRedirect)"
        }
        return urlString
    }

    func getPhotosAuthUrl(redirectUri: String? = nil) -> String {
        var urlString = "\(baseURL)/integrations/photos/auth"
        if let redirectUri = redirectUri {
            guard let encodedRedirect = redirectUri.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) else {
                return urlString
            }
            urlString += "?redirect_uri=\(encodedRedirect)"
        }
        return urlString
    }

    // MARK: - Health Check

    func checkHealth() async throws -> HealthResponse {
        guard let url = URL(string: "\(baseURL)/health") else {
            throw BackendAPIError.invalidResponse
        }

        let (data, _) = try await URLSession.shared.data(from: url)
        return try decoder.decode(HealthResponse.self, from: data)
    }
}
