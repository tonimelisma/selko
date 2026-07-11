package net.melisma.selko.data.repository

import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.postgrest.from
import io.github.jan.supabase.postgrest.query.Columns
import io.github.jan.supabase.postgrest.query.Order
import net.melisma.selko.data.model.Integration
import net.melisma.selko.data.model.IntegrationProvider

sealed class IntegrationResult<out T> {
    data class Success<T>(val data: T) : IntegrationResult<T>()
    data class Error(val message: String) : IntegrationResult<Nothing>()
}

class IntegrationRepository(
    private val supabaseClient: SupabaseClient
) {
    // Select only safe fields (excluding tokens)
    private val safeColumns = Columns.list(
        "id", "user_id", "provider", "status", "provider_email",
        "scopes", "last_sync_at", "created_at", "updated_at"
    )

    private fun providerToString(provider: IntegrationProvider): String = when (provider) {
        IntegrationProvider.GMAIL -> "gmail"
        IntegrationProvider.OUTLOOK -> "outlook"
        IntegrationProvider.GOOGLE_PHOTOS -> "google_photos"
        IntegrationProvider.GOOGLE_CALENDAR -> "google_calendar"
    }

    suspend fun fetchIntegrations(): IntegrationResult<List<Integration>> {
        return try {
            val integrations = supabaseClient.from("integrations")
                .select(safeColumns) {
                    order("created_at", Order.DESCENDING)
                }
                .decodeList<Integration>()

            IntegrationResult.Success(integrations)
        } catch (e: Exception) {
            IntegrationResult.Error(e.message ?: "Failed to fetch integrations")
        }
    }

    suspend fun getIntegration(integrationId: String): IntegrationResult<Integration> {
        return try {
            val integration = supabaseClient.from("integrations")
                .select(safeColumns) {
                    filter {
                        eq("id", integrationId)
                    }
                }
                .decodeSingle<Integration>()

            IntegrationResult.Success(integration)
        } catch (e: Exception) {
            IntegrationResult.Error(e.message ?: "Failed to fetch integration")
        }
    }

    suspend fun getIntegrationByProvider(provider: IntegrationProvider): IntegrationResult<Integration?> {
        return try {
            val integration = supabaseClient.from("integrations")
                .select(safeColumns) {
                    filter {
                        eq("provider", providerToString(provider))
                    }
                }
                .decodeSingleOrNull<Integration>()

            IntegrationResult.Success(integration)
        } catch (e: Exception) {
            IntegrationResult.Error(e.message ?: "Failed to fetch integration")
        }
    }

    suspend fun isProviderConnected(provider: IntegrationProvider): Boolean {
        return when (val result = getIntegrationByProvider(provider)) {
            is IntegrationResult.Success -> result.data?.isActive == true
            is IntegrationResult.Error -> false
        }
    }

    suspend fun deleteIntegration(provider: IntegrationProvider): IntegrationResult<Unit> {
        return try {
            supabaseClient.from("integrations")
                .delete {
                    filter {
                        eq("provider", providerToString(provider))
                    }
                }

            IntegrationResult.Success(Unit)
        } catch (e: Exception) {
            IntegrationResult.Error(e.message ?: "Failed to delete integration")
        }
    }
}
