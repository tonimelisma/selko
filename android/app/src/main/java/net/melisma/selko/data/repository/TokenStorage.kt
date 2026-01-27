package net.melisma.selko.data.repository

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "auth_tokens")

class TokenStorage(private val context: Context) {
    private val accessTokenKey = stringPreferencesKey("access_token")
    private val refreshTokenKey = stringPreferencesKey("refresh_token")
    private val userEmailKey = stringPreferencesKey("user_email")
    private val userIdKey = stringPreferencesKey("user_id")

    val accessToken: Flow<String?> = context.dataStore.data.map { preferences ->
        preferences[accessTokenKey]
    }

    val userEmail: Flow<String?> = context.dataStore.data.map { preferences ->
        preferences[userEmailKey]
    }

    val userId: Flow<String?> = context.dataStore.data.map { preferences ->
        preferences[userIdKey]
    }

    val isLoggedIn: Flow<Boolean> = context.dataStore.data.map { preferences ->
        preferences[accessTokenKey] != null
    }

    suspend fun saveTokens(
        accessToken: String,
        refreshToken: String,
        userEmail: String?,
        userId: String
    ) {
        context.dataStore.edit { preferences ->
            preferences[accessTokenKey] = accessToken
            preferences[refreshTokenKey] = refreshToken
            userEmail?.let { preferences[userEmailKey] = it }
            preferences[userIdKey] = userId
        }
    }

    suspend fun getAccessToken(): String? {
        return context.dataStore.data.first()[accessTokenKey]
    }

    suspend fun clearTokens() {
        context.dataStore.edit { preferences ->
            preferences.remove(accessTokenKey)
            preferences.remove(refreshTokenKey)
            preferences.remove(userEmailKey)
            preferences.remove(userIdKey)
        }
    }
}
