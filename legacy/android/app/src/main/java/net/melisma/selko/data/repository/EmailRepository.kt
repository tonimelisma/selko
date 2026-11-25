package net.melisma.selko.data.repository

import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.postgrest.from
import io.github.jan.supabase.postgrest.query.Order
import net.melisma.selko.data.model.Email

sealed class EmailResult<out T> {
    data class Success<T>(val data: T) : EmailResult<T>()
    data class Error(val message: String) : EmailResult<Nothing>()
}

data class FetchEmailsOptions(
    val limit: Int = 50,
    val offset: Int = 0,
    val excludeSpam: Boolean = true,
    val excludeTrash: Boolean = true,
    val excludePromotions: Boolean = false,
    val unreadOnly: Boolean = false
)

class EmailRepository(
    private val supabaseClient: SupabaseClient
) {
    suspend fun fetchEmails(options: FetchEmailsOptions = FetchEmailsOptions()): EmailResult<List<Email>> {
        return try {
            val emails = supabaseClient.from("emails")
                .select {
                    filter {
                        if (options.excludeSpam) {
                            eq("is_spam", false)
                        }
                        if (options.excludeTrash) {
                            eq("is_trash", false)
                        }
                        if (options.excludePromotions) {
                            eq("is_promotions", false)
                        }
                        if (options.unreadOnly) {
                            eq("is_unread", true)
                        }
                    }
                    order("date_sent", Order.DESCENDING)
                    range(options.offset.toLong(), (options.offset + options.limit - 1).toLong())
                }
                .decodeList<Email>()

            EmailResult.Success(emails)
        } catch (e: Exception) {
            EmailResult.Error(e.message ?: "Failed to fetch emails")
        }
    }

    suspend fun getEmail(emailId: String): EmailResult<Email> {
        return try {
            val email = supabaseClient.from("emails")
                .select {
                    filter {
                        eq("id", emailId)
                    }
                }
                .decodeSingle<Email>()

            EmailResult.Success(email)
        } catch (e: Exception) {
            EmailResult.Error(e.message ?: "Failed to fetch email")
        }
    }

    suspend fun updateEmailReadStatus(emailId: String, isUnread: Boolean): EmailResult<Email> {
        return try {
            val email = supabaseClient.from("emails")
                .update(mapOf("is_unread" to isUnread)) {
                    select()
                    filter {
                        eq("id", emailId)
                    }
                }
                .decodeSingle<Email>()

            EmailResult.Success(email)
        } catch (e: Exception) {
            EmailResult.Error(e.message ?: "Failed to update email")
        }
    }
}
