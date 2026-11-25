package net.melisma.selko.data.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlin.time.Instant

@Serializable
data class Email(
    val id: String,
    @SerialName("user_id") val userId: String? = null,
    @SerialName("integration_id") val integrationId: String? = null,
    @SerialName("email_provider") val emailProvider: String? = null,
    @SerialName("provider_message_id") val providerMessageId: String? = null,
    @SerialName("thread_id") val threadId: String? = null,
    val subject: String? = null,
    @SerialName("from_email") val fromEmail: String? = null,
    @SerialName("from_name") val fromName: String? = null,
    @SerialName("to_emails") val toEmails: List<String>? = null,
    @SerialName("date_sent") val dateSent: Instant? = null,
    val snippet: String? = null,
    @SerialName("provider_labels") val providerLabels: List<String> = emptyList(),
    @SerialName("is_spam") val isSpam: Boolean = false,
    @SerialName("is_trash") val isTrash: Boolean = false,
    @SerialName("is_promotions") val isPromotions: Boolean = false,
    @SerialName("is_social") val isSocial: Boolean = false,
    @SerialName("is_updates") val isUpdates: Boolean = false,
    @SerialName("is_forums") val isForums: Boolean = false,
    @SerialName("is_primary") val isPrimary: Boolean = false,
    @SerialName("is_important") val isImportant: Boolean = false,
    @SerialName("is_starred") val isStarred: Boolean = false,
    @SerialName("is_unread") val isUnread: Boolean = false,
    @SerialName("has_attachments") val hasAttachments: Boolean = false,
    @SerialName("created_at") val createdAt: Instant? = null
) {
    val displaySender: String
        get() = fromName ?: fromEmail ?: "Unknown"
}
