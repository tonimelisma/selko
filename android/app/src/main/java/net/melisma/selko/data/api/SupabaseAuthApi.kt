package net.melisma.selko.data.api

import io.ktor.client.HttpClient
import io.ktor.client.call.body
import io.ktor.client.request.header
import io.ktor.client.request.post
import io.ktor.client.request.setBody
import io.ktor.http.ContentType
import io.ktor.http.contentType
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import net.melisma.selko.BuildConfig

@Serializable
data class SignUpRequest(
    val email: String,
    val password: String
)

@Serializable
data class SignInRequest(
    val email: String,
    val password: String
)

@Serializable
data class AuthResponse(
    @SerialName("access_token")
    val accessToken: String,
    @SerialName("token_type")
    val tokenType: String,
    @SerialName("expires_in")
    val expiresIn: Int,
    @SerialName("refresh_token")
    val refreshToken: String,
    val user: UserInfo
)

@Serializable
data class UserInfo(
    val id: String,
    val email: String? = null,
    @SerialName("created_at")
    val createdAt: String? = null
)

@Serializable
data class AuthError(
    val error: String? = null,
    @SerialName("error_description")
    val errorDescription: String? = null,
    val message: String? = null,
    val msg: String? = null
) {
    fun getDisplayMessage(): String {
        return errorDescription ?: error ?: message ?: msg ?: "Unknown error"
    }
}

class SupabaseAuthApi(private val client: HttpClient) {
    private val baseUrl = BuildConfig.SUPABASE_URL
    private val anonKey = BuildConfig.SUPABASE_ANON_KEY

    suspend fun signUp(email: String, password: String): Result<AuthResponse> {
        return try {
            val response = client.post("$baseUrl/auth/v1/signup") {
                contentType(ContentType.Application.Json)
                header("apikey", anonKey)
                setBody(SignUpRequest(email, password))
            }
            Result.success(response.body())
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun signIn(email: String, password: String): Result<AuthResponse> {
        return try {
            val response = client.post("$baseUrl/auth/v1/token?grant_type=password") {
                contentType(ContentType.Application.Json)
                header("apikey", anonKey)
                setBody(SignInRequest(email, password))
            }
            Result.success(response.body())
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
}
