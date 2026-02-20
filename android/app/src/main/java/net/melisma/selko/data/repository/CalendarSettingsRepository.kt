package net.melisma.selko.data.repository

import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.postgrest.from
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class CalendarSettings(
    @SerialName("user_id") val userId: String? = null,
    @SerialName("target_calendar_id") val targetCalendarId: String? = null,
    @SerialName("default_invitees") val defaultInvitees: String? = null,
    @SerialName("updated_at") val updatedAt: String? = null
)

class CalendarSettingsRepository(private val supabaseClient: SupabaseClient) {

    suspend fun getSettings(): RepositoryResult<CalendarSettings?> {
        return try {
            val settings = supabaseClient.from("user_calendar_settings")
                .select()
                .decodeSingleOrNull<CalendarSettings>()
            RepositoryResult.Success(settings)
        } catch (e: Exception) {
            RepositoryResult.Error(e.message ?: "Failed to fetch calendar settings")
        }
    }

    suspend fun updateSettings(
        targetCalendarId: String?,
        defaultInvitees: String?
    ): RepositoryResult<CalendarSettings> {
        return try {
            val updates = mutableMapOf<String, Any?>()
            targetCalendarId?.let { updates["target_calendar_id"] = it }
            defaultInvitees?.let { updates["default_invitees"] = it }

            val settings = supabaseClient.from("user_calendar_settings")
                .upsert(updates) {
                    select()
                }
                .decodeSingle<CalendarSettings>()
            RepositoryResult.Success(settings)
        } catch (e: Exception) {
            RepositoryResult.Error(e.message ?: "Failed to update calendar settings")
        }
    }
}
