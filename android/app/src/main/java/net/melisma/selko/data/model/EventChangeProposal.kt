package net.melisma.selko.data.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject
import kotlin.time.Instant

@Serializable
enum class EventChangeProposalKind {
    @SerialName("material_update") MATERIAL_UPDATE,
    CANCELLATION
}

@Serializable
enum class EventChangeProposalStatus {
    @SerialName("pending") PENDING,
    @SerialName("applied") APPLIED,
    @SerialName("rejected") REJECTED,
    @SerialName("superseded") SUPERSEDED,
    @SerialName("closed_legacy") CLOSED_LEGACY
}

@Serializable
data class EventChangeProposal(
    val id: String,
    @SerialName("event_id") val eventId: String,
    @SerialName("user_id") val userId: String,
    @SerialName("source_id") val sourceId: String,
    val kind: EventChangeProposalKind,
    val status: EventChangeProposalStatus,
    @SerialName("change_set") val changeSet: EventChangeSet,
    @SerialName("event_snapshot_before") val eventSnapshotBefore: JsonObject? = null,
    @SerialName("resolution_reason") val resolutionReason: String? = null,
    @SerialName("created_at") val createdAt: Instant? = null,
    @SerialName("resolved_at") val resolvedAt: Instant? = null,
    @SerialName("updated_at") val updatedAt: Instant? = null
)
