package net.melisma.selko.data.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class SenderRule(
    val id: String,
    @SerialName("user_id") val userId: String,
    @SerialName("sender_email") val senderEmail: String? = null,
    @SerialName("sender_domain") val senderDomain: String? = null,
    val action: String, // "auto_approve" or "ignore"
    @SerialName("created_at") val createdAt: String
)
