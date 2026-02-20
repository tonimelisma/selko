package net.melisma.selko.data.repository

import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.auth.auth
import io.github.jan.supabase.postgrest.from
import io.github.jan.supabase.postgrest.query.Order
import net.melisma.selko.data.model.SenderRule

class SenderRuleRepository(
    private val supabaseClient: SupabaseClient
) {
    suspend fun fetchRules(): Result<List<SenderRule>> {
        return runCatching {
            supabaseClient.from("sender_rules")
                .select {
                    order("created_at", Order.DESCENDING)
                }
                .decodeList<SenderRule>()
        }
    }

    suspend fun createRule(
        senderEmail: String?,
        senderDomain: String?,
        action: String
    ): Result<SenderRule> {
        return runCatching {
            val userId = supabaseClient.auth.currentUserOrNull()?.id
                ?: throw IllegalStateException("User not authenticated")

            val data = mutableMapOf<String, Any>(
                "user_id" to userId,
                "action" to action
            )
            senderEmail?.let { data["sender_email"] = it }
            senderDomain?.let { data["sender_domain"] = it }

            supabaseClient.from("sender_rules")
                .insert(data) {
                    select()
                }
                .decodeSingle<SenderRule>()
        }
    }

    suspend fun deleteRule(id: String): Result<Unit> {
        return runCatching {
            supabaseClient.from("sender_rules")
                .delete {
                    filter {
                        eq("id", id)
                    }
                }
        }
    }
}
