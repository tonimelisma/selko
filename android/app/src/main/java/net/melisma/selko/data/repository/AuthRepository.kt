package net.melisma.selko.data.repository

import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.auth.auth
import io.github.jan.supabase.auth.providers.builtin.Email
import io.github.jan.supabase.auth.status.SessionStatus
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

sealed class AuthResult {
    data class Success(val email: String?) : AuthResult()
    data class Error(val message: String) : AuthResult()
}

class AuthRepository(
    private val supabaseClient: SupabaseClient
) {
    val sessionStatus: Flow<SessionStatus> = supabaseClient.auth.sessionStatus

    val isLoggedIn: Flow<Boolean> = sessionStatus.map { status ->
        status is SessionStatus.Authenticated
    }

    val userEmail: Flow<String?> = sessionStatus.map { status ->
        when (status) {
            is SessionStatus.Authenticated -> status.session.user?.email
            else -> null
        }
    }

    suspend fun signUp(email: String, password: String): AuthResult {
        return try {
            supabaseClient.auth.signUpWith(Email) {
                this.email = email
                this.password = password
            }
            val currentUser = supabaseClient.auth.currentUserOrNull()
            AuthResult.Success(currentUser?.email)
        } catch (e: Exception) {
            AuthResult.Error(e.message ?: "Sign up failed")
        }
    }

    suspend fun signIn(email: String, password: String): AuthResult {
        return try {
            supabaseClient.auth.signInWith(Email) {
                this.email = email
                this.password = password
            }
            val currentUser = supabaseClient.auth.currentUserOrNull()
            AuthResult.Success(currentUser?.email)
        } catch (e: Exception) {
            AuthResult.Error(e.message ?: "Sign in failed")
        }
    }

    suspend fun signOut() {
        try {
            supabaseClient.auth.signOut()
        } catch (e: Exception) {
            // Ignore errors during sign out
        }
    }

    suspend fun getAccessToken(): String? {
        return supabaseClient.auth.currentAccessTokenOrNull()
    }

    fun getCurrentUserEmail(): String? {
        return supabaseClient.auth.currentUserOrNull()?.email
    }
}
