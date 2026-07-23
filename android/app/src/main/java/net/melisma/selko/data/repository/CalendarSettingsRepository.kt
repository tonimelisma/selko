package net.melisma.selko.data.repository

import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.postgrest.from
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

enum class AllDayDisplayMode(val value: String) {
    ALL_DAY("all_day"),
    DAY_9_TO_5("day_9_to_5"),
    MORNING_8_TO_9("morning_8_to_9"),
    CUSTOM("custom");

    companion object {
        fun fromValue(value: String?): AllDayDisplayMode {
            return entries.firstOrNull { it.value == value } ?: ALL_DAY
        }
    }
}

@Serializable
data class CalendarSettings(
    @SerialName("user_id") val userId: String? = null,
    @SerialName("target_calendar_id") val targetCalendarId: String? = null,
    @SerialName("default_invitees") val defaultInvitees: String? = null,
    @SerialName("all_day_display_mode") val allDayDisplayMode: String? = null,
    @SerialName("all_day_custom_start") val allDayCustomStart: String? = null,
    @SerialName("all_day_custom_end") val allDayCustomEnd: String? = null,
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
        targetCalendarId: String? = null,
        defaultInvitees: String? = null,
        allDayDisplayMode: String? = null,
        allDayCustomStart: String? = null,
        allDayCustomEnd: String? = null
    ): RepositoryResult<CalendarSettings> {
        return try {
            val updates = mutableMapOf<String, Any?>()
            targetCalendarId?.let { updates["target_calendar_id"] = it }
            defaultInvitees?.let { updates["default_invitees"] = it }
            allDayDisplayMode?.let { updates["all_day_display_mode"] = it }
            // Only write custom times in custom mode so preset switches preserve them.
            if (allDayDisplayMode == AllDayDisplayMode.CUSTOM.value) {
                allDayCustomStart?.let { updates["all_day_custom_start"] = it }
                allDayCustomEnd?.let { updates["all_day_custom_end"] = it }
            }

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
