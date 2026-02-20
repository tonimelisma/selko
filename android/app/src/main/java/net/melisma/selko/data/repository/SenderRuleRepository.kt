package net.melisma.selko.data.repository

import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.auth.auth
import io.github.jan.supabase.postgrest.from
import io.github.jan.supabase.postgrest.query.Order
import net.melisma.selko.data.model.SenderRule

class SenderRuleRepository(
    private val supabaseClient: SupabaseClient
) {
    suspend fun fetchRules(): RepositoryResult<List<SenderRule>> {
        return try {
            val rules = supabaseClient.from("sender_rules")
                .select {
                    order("created_at", Order.DESCENDING)
                }
                .decodeList<SenderRule>()
            RepositoryResult.Success(rules)
        } catch (e: Exception) {
            RepositoryResult.Error(e.message ?: "Failed to fetch sender rules")
        }
    }

    suspend fun createRule(
        senderEmail: String?,
        senderDomain: String?,
        action: String
    ): RepositoryResult<SenderRule> {
        return try {
            val userId = supabaseClient.auth.currentUserOrNull()?.id
                ?: throw IllegalStateException("User not authenticated")

            val data = mutableMapOf<String, Any>(
                "user_id" to userId,
                "action" to action
            )
            senderEmail?.let { data["sender_email"] = it }
            senderDomain?.let { data["sender_domain"] = it }

            val rule = supabaseClient.from("sender_rules")
                .insert(data) {
                    select()
                }
                .decodeSingle<SenderRule>()
            RepositoryResult.Success(rule)
        } catch (e: Exception) {
            RepositoryResult.Error(e.message ?: "Failed to create sender rule")
        }
    }

    suspend fun deleteRule(id: String): RepositoryResult<Unit> {
        return try {
            supabaseClient.from("sender_rules")
                .delete {
                    filter {
                        eq("id", id)
                    }
                }
            RepositoryResult.Success(Unit)
        } catch (e: Exception) {
            RepositoryResult.Error(e.message ?: "Failed to delete sender rule")
        }
    }
}
