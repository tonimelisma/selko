package net.melisma.selko.data.repository

import kotlinx.coroutines.flow.Flow
import net.melisma.selko.data.api.AuthResponse
import net.melisma.selko.data.api.SupabaseAuthApi

sealed class AuthResult {
    data class Success(val email: String?) : AuthResult()
    data class Error(val message: String) : AuthResult()
}

class AuthRepository(
    private val authApi: SupabaseAuthApi,
    private val tokenStorage: TokenStorage
) {
    val isLoggedIn: Flow<Boolean> = tokenStorage.isLoggedIn
    val userEmail: Flow<String?> = tokenStorage.userEmail

    suspend fun signUp(email: String, password: String): AuthResult {
        val result = authApi.signUp(email, password)
        return result.fold(
            onSuccess = { response ->
                saveAuthResponse(response)
                AuthResult.Success(response.user.email)
            },
            onFailure = { exception ->
                AuthResult.Error(exception.message ?: "Sign up failed")
            }
        )
    }

    suspend fun signIn(email: String, password: String): AuthResult {
        val result = authApi.signIn(email, password)
        return result.fold(
            onSuccess = { response ->
                saveAuthResponse(response)
                AuthResult.Success(response.user.email)
            },
            onFailure = { exception ->
                AuthResult.Error(exception.message ?: "Sign in failed")
            }
        )
    }

    suspend fun signOut() {
        tokenStorage.clearTokens()
    }

    suspend fun getAccessToken(): String? {
        return tokenStorage.getAccessToken()
    }

    private suspend fun saveAuthResponse(response: AuthResponse) {
        tokenStorage.saveTokens(
            accessToken = response.accessToken,
            refreshToken = response.refreshToken,
            userEmail = response.user.email,
            userId = response.user.id
        )
    }
}
