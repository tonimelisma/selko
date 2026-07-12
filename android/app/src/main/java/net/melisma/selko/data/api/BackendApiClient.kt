package net.melisma.selko.data.api

import io.ktor.client.*
import io.ktor.client.call.*
import io.ktor.client.engine.okhttp.*
import io.ktor.client.plugins.*
import io.ktor.client.plugins.contentnegotiation.*
import io.ktor.client.request.*
import io.ktor.http.*
import io.ktor.serialization.kotlinx.json.*
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import net.melisma.selko.BuildConfig
import net.melisma.selko.data.repository.AuthRepository

/**
 * Backend API client for server-side operations that require secrets.
 *
 * Use this for:
 * - Email sync (requires Gmail API credentials)
 * - Email processing (requires Gemini API key)
 * - Calendar sync (requires Google Calendar API credentials)
 * - OAuth flows (requires client secrets)
 */
class BackendApiClient(
    private val authRepository: AuthRepository
) {
    private val json = Json {
        ignoreUnknownKeys = true
        isLenient = true
    }

    private val httpClient = HttpClient(OkHttp) {
        install(ContentNegotiation) {
            json(json)
        }
        install(HttpTimeout) {
            requestTimeoutMillis = 60_000
            connectTimeoutMillis = 15_000
        }
        defaultRequest {
            contentType(ContentType.Application.Json)
        }
    }

    private val baseUrl: String
        get() = BuildConfig.SELKO_API_URL

    private suspend fun getAuthHeader(): String? {
        val token = authRepository.getAccessToken()
        return token?.let { "Bearer $it" }
    }

    // ============================================================================
    // Email Operations
    // ============================================================================

    @Serializable
    data class EmailSyncRequest(
        val max_results: Int = 50,
        val fetch_attachments: Boolean = true
    )

    @Serializable
    data class EmailSyncResponse(
        val fetched: Int,
        val saved: Int,
        val attachments_downloaded: Int? = null
    )

    suspend fun syncEmails(
        maxResults: Int = 50,
        fetchAttachments: Boolean = true
    ): Result<EmailSyncResponse> {
        return try {
            val authHeader = getAuthHeader()
                ?: return Result.failure(Exception("Not authenticated"))

            val response = httpClient.post("$baseUrl/emails/sync") {
                header(HttpHeaders.Authorization, authHeader)
                setBody(EmailSyncRequest(maxResults, fetchAttachments))
            }

            if (response.status.isSuccess()) {
                Result.success(response.body())
            } else {
                val errorMessage = try {
                    response.body<ApiErrorResponse>().detail ?: "Sync failed"
                } catch (_: Exception) {
                    "Request failed with status ${response.status.value}"
                }
                Result.failure(Exception(errorMessage))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    @Serializable
    data class EmailProcessResponse(
        val num_events: Int,
        val num_new: Int,
        val num_updated: Int,
        val event_ids: List<String>
    )

    suspend fun processEmail(emailId: String): Result<EmailProcessResponse> {
        return try {
            val authHeader = getAuthHeader()
                ?: return Result.failure(Exception("Not authenticated"))

            val response = httpClient.post("$baseUrl/emails/$emailId/process") {
                header(HttpHeaders.Authorization, authHeader)
            }

            if (response.status.isSuccess()) {
                Result.success(response.body())
            } else {
                val errorMessage = try {
                    response.body<ApiErrorResponse>().detail ?: "Processing failed"
                } catch (_: Exception) {
                    "Request failed with status ${response.status.value}"
                }
                Result.failure(Exception(errorMessage))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    @Serializable
    data class BatchProcessRequest(
        val max_emails: Int = 10
    )

    suspend fun batchProcessEmails(maxEmails: Int = 10): Result<EmailProcessResponse> {
        return try {
            val authHeader = getAuthHeader()
                ?: return Result.failure(Exception("Not authenticated"))

            val response = httpClient.post("$baseUrl/emails/batch-process") {
                header(HttpHeaders.Authorization, authHeader)
                setBody(BatchProcessRequest(maxEmails))
            }

            if (response.status.isSuccess()) {
                Result.success(response.body())
            } else {
                val errorMessage = try {
                    response.body<ApiErrorResponse>().detail ?: "Batch processing failed"
                } catch (_: Exception) {
                    "Request failed with status ${response.status.value}"
                }
                Result.failure(Exception(errorMessage))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    // ============================================================================
    // Calendar Operations
    // ============================================================================

    @Serializable
    data class Calendar(
        val id: String,
        val name: String,
        val is_primary: Boolean,
        val is_selected: Boolean
    )

    suspend fun listCalendars(): Result<List<Calendar>> {
        return try {
            val authHeader = getAuthHeader()
                ?: return Result.failure(Exception("Not authenticated"))

            val response = httpClient.get("$baseUrl/calendars") {
                header(HttpHeaders.Authorization, authHeader)
            }

            if (response.status.isSuccess()) {
                Result.success(response.body())
            } else {
                val errorMessage = try {
                    response.body<ApiErrorResponse>().detail ?: "Failed to list calendars"
                } catch (_: Exception) {
                    "Request failed with status ${response.status.value}"
                }
                Result.failure(Exception(errorMessage))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    @Serializable
    data class CalendarSyncResponse(
        val event_id: String,
        val google_calendar_event_id: String,
        val synced_at: String,
        val status: String
    )

    suspend fun syncEventToCalendar(eventId: String): Result<CalendarSyncResponse> {
        return try {
            val authHeader = getAuthHeader()
                ?: return Result.failure(Exception("Not authenticated"))

            val response = httpClient.post("$baseUrl/events/$eventId/sync") {
                header(HttpHeaders.Authorization, authHeader)
            }

            if (response.status.isSuccess()) {
                Result.success(response.body())
            } else {
                val errorMessage = try {
                    response.body<ApiErrorResponse>().detail ?: "Calendar sync failed"
                } catch (_: Exception) {
                    "Request failed with status ${response.status.value}"
                }
                Result.failure(Exception(errorMessage))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    @Serializable
    data class EventChangeResponse(
        val event_id: String,
        val status: String
    )

    suspend fun applyEventChange(eventId: String): Result<EventChangeResponse> {
        return try {
            val authHeader = getAuthHeader()
                ?: return Result.failure(Exception("Not authenticated"))
            val response = httpClient.post("$baseUrl/events/$eventId/apply-change") {
                header(HttpHeaders.Authorization, authHeader)
            }
            if (response.status.isSuccess()) {
                Result.success(response.body())
            } else {
                Result.failure(Exception("Apply change failed (${response.status.value})"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun rejectEventChange(eventId: String): Result<EventChangeResponse> {
        return try {
            val authHeader = getAuthHeader()
                ?: return Result.failure(Exception("Not authenticated"))
            val response = httpClient.post("$baseUrl/events/$eventId/reject-change") {
                header(HttpHeaders.Authorization, authHeader)
            }
            if (response.status.isSuccess()) {
                Result.success(response.body())
            } else {
                Result.failure(Exception("Reject change failed (${response.status.value})"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    @Serializable
    data class UndoHistoryRequest(
        val force: Boolean = false
    )

    @Serializable
    data class ApiErrorDetail(
        val error: String? = null,
        val detail: String? = null
    )

    @Serializable
    data class ApiErrorBody(
        val detail: ApiErrorDetail? = null,
        val message: String? = null,
        val error: String? = null
    )

    class CalendarDivergedException(message: String) : Exception(message)

    suspend fun undoHistoryEvent(
        eventId: String,
        force: Boolean = false
    ): Result<EventChangeResponse> {
        return try {
            val authHeader = getAuthHeader()
                ?: return Result.failure(Exception("Not authenticated"))
            val response = httpClient.post("$baseUrl/events/$eventId/undo") {
                header(HttpHeaders.Authorization, authHeader)
                setBody(UndoHistoryRequest(force = force))
                expectSuccess = false
            }
            if (response.status.isSuccess()) {
                Result.success(response.body())
            } else {
                val bodyText = try {
                    response.body<String>()
                } catch (_: Exception) {
                    null
                }
                val parsed = bodyText?.let {
                    try {
                        json.decodeFromString<ApiErrorBody>(it)
                    } catch (_: Exception) {
                        null
                    }
                }
                val message = parsed?.detail?.detail
                    ?: parsed?.message
                    ?: "Undo failed (${response.status.value})"
                if (response.status.value == 409 ||
                    parsed?.detail?.error == "CALENDAR_DIVERGED" ||
                    parsed?.error == "CALENDAR_DIVERGED"
                ) {
                    Result.failure(CalendarDivergedException(message))
                } else {
                    Result.failure(Exception(message))
                }
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    // ============================================================================
    // OAuth Operations
    // ============================================================================

    /**
     * Get the Gmail OAuth authorization URL.
     * User should be redirected to this URL in a web browser.
     */
    fun getGmailAuthUrl(redirectUri: String? = null): String {
        val params = redirectUri?.let { "?redirect_uri=$it" } ?: ""
        return "$baseUrl/integrations/gmail/auth$params"
    }

    /**
     * Get the Microsoft Graph / Outlook OAuth authorization URL.
     */
    fun getOutlookAuthUrl(redirectUri: String? = null): String {
        val params = redirectUri?.let { "?redirect_uri=$it" } ?: ""
        return "$baseUrl/integrations/outlook/auth$params"
    }

    /**
     * Get the Google Calendar OAuth authorization URL.
     * User should be redirected to this URL in a web browser.
     */
    fun getCalendarAuthUrl(redirectUri: String? = null): String {
        val params = redirectUri?.let { "?redirect_uri=$it" } ?: ""
        return "$baseUrl/integrations/calendar/auth$params"
    }

    /**
     * Get the Google Photos OAuth authorization URL.
     * User should be redirected to this URL in a web browser.
     */
    fun getPhotosAuthUrl(redirectUri: String? = null): String {
        val params = redirectUri?.let { "?redirect_uri=$it" } ?: ""
        return "$baseUrl/integrations/photos/auth$params"
    }

    // ============================================================================
    // Health Check
    // ============================================================================

    @Serializable
    data class HealthResponse(
        val status: String
    )

    suspend fun checkHealth(): Result<HealthResponse> {
        return try {
            val response = httpClient.get("$baseUrl/health")

            if (response.status.isSuccess()) {
                Result.success(response.body())
            } else {
                Result.failure(Exception("Health check failed: ${response.status}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    // ============================================================================
    // Error Response
    // ============================================================================

    @Serializable
    private data class ApiErrorResponse(
        val detail: String? = null,
        val message: String? = null
    )
}
