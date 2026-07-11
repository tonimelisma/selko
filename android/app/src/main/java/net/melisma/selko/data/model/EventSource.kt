package net.melisma.selko.data.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject
import kotlin.time.Instant

@Serializable
enum class SourceType {
    @SerialName("new_invitation") NEW_INVITATION,
    @SerialName("update") UPDATE,
    @SerialName("cancellation") CANCELLATION,
    @SerialName("reminder") REMINDER,
    @SerialName("unknown") UNKNOWN
}

@Serializable
data class ExtractedData(
    val title: String? = null,
    @SerialName("start_datetime") val startDatetime: String? = null,
    @SerialName("end_datetime") val endDatetime: String? = null,
    val location: String? = null,
    val description: String? = null,
    @SerialName("source_quote") val sourceQuote: String? = null
)

@Serializable
enum class SourceOrigin {
    @SerialName("email") EMAIL,
    @SerialName("google_calendar") GOOGLE_CALENDAR,
    @SerialName("google_photos") GOOGLE_PHOTOS
}

@Serializable
data class FieldChange(
    val field: String,
    val before: String? = null,
    val after: String? = null,
    val reason: String? = null
)

@Serializable
data class EventChangeSet(
    val kind: String? = null,
    val changes: List<FieldChange> = emptyList(),
    val reasoning: String? = null
)

@Serializable
data class EventSource(
    val id: String,
    @SerialName("event_id") val eventId: String,
    @SerialName("email_id") val emailId: String? = null,
    @SerialName("source_origin") val sourceOrigin: SourceOrigin = SourceOrigin.EMAIL,
    @SerialName("source_type") val sourceType: SourceType = SourceType.UNKNOWN,
    @SerialName("extracted_data") val extractedData: ExtractedData? = null,
    @SerialName("event_snapshot_before") val eventSnapshotBefore: JsonObject? = null,
    @SerialName("change_set") val changeSet: EventChangeSet? = null,
    @SerialName("is_undone") val isUndone: Boolean = false,
    @SerialName("created_at") val createdAt: Instant? = null,
    // Joined email data
    val emails: Email? = null
)
