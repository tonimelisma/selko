package net.melisma.selko.data.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class EmailFolderPreference(
    val id: String,
    val provider: String,
    val name: String,
    @SerialName("full_path") val fullPath: String,
    @SerialName("classification_decision") val classificationDecision: String,
    @SerialName("classification_reason") val classificationReason: String? = null,
    @SerialName("user_override") val userOverride: Boolean,
    @SerialName("is_included") val isIncluded: Boolean,
    @SerialName("is_system") val isSystem: Boolean
)
