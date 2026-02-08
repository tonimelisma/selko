package net.melisma.selko.ui.screens.settings

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import net.melisma.selko.data.api.BackendApiClient
import net.melisma.selko.data.model.Integration
import net.melisma.selko.data.model.IntegrationProvider
import net.melisma.selko.data.repository.AuthRepository
import net.melisma.selko.data.repository.CalendarSettings
import net.melisma.selko.data.repository.CalendarSettingsRepository
import net.melisma.selko.data.repository.IntegrationRepository
import net.melisma.selko.data.repository.IntegrationResult

data class SettingsUiState(
    val isLoading: Boolean = true,
    val userEmail: String? = null,
    val integrations: List<Integration> = emptyList(),
    val calendars: List<BackendApiClient.Calendar> = emptyList(),
    val calendarSettings: CalendarSettings? = null,
    val selectedCalendarId: String? = null,
    val defaultInvitees: String = "",
    val errorMessage: String? = null,
    val isDisconnecting: Boolean = false,
    val isSigningOut: Boolean = false,
    val isSavingCalendarSettings: Boolean = false
)

class SettingsViewModel(
    private val authRepository: AuthRepository,
    private val integrationRepository: IntegrationRepository,
    private val calendarSettingsRepository: CalendarSettingsRepository,
    private val backendApiClient: BackendApiClient
) : ViewModel() {

    private val _uiState = MutableStateFlow(SettingsUiState())
    val uiState: StateFlow<SettingsUiState> = _uiState.asStateFlow()

    init {
        loadSettings()
    }

    private fun loadSettings() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true) }

            // Load user email
            val email = authRepository.getCurrentUserEmail()
            _uiState.update { it.copy(userEmail = email) }

            // Load integrations
            when (val result = integrationRepository.fetchIntegrations()) {
                is IntegrationResult.Success -> {
                    _uiState.update { it.copy(integrations = result.data) }
                }
                is IntegrationResult.Error -> {
                    _uiState.update { it.copy(errorMessage = result.message) }
                }
            }

            // Load calendars
            try {
                val calendarsResult = backendApiClient.listCalendars()
                calendarsResult.onSuccess { calendars ->
                    _uiState.update { it.copy(calendars = calendars) }
                }
            } catch (e: Exception) {
                // Calendars may not be available if not connected
            }

            // Load calendar settings
            try {
                val settingsResult = calendarSettingsRepository.getSettings()
                settingsResult.onSuccess { settings ->
                    _uiState.update {
                        it.copy(
                            calendarSettings = settings,
                            selectedCalendarId = settings?.targetCalendarId,
                            defaultInvitees = settings?.defaultInvitees ?: ""
                        )
                    }
                }
            } catch (e: Exception) {
                // Settings may not exist yet
            }

            _uiState.update { it.copy(isLoading = false) }
        }
    }

    fun disconnectIntegration(provider: IntegrationProvider) {
        viewModelScope.launch {
            _uiState.update { it.copy(isDisconnecting = true) }

            when (integrationRepository.deleteIntegration(provider)) {
                is IntegrationResult.Success -> {
                    _uiState.update { state ->
                        state.copy(
                            isDisconnecting = false,
                            integrations = state.integrations.filter { it.provider != provider }
                        )
                    }
                }
                is IntegrationResult.Error -> {
                    _uiState.update {
                        it.copy(
                            isDisconnecting = false,
                            errorMessage = "Failed to disconnect"
                        )
                    }
                }
            }
        }
    }

    fun onCalendarSelected(calendarId: String) {
        _uiState.update { it.copy(selectedCalendarId = calendarId) }
        saveCalendarSettings()
    }

    fun onDefaultInviteesChange(value: String) {
        _uiState.update { it.copy(defaultInvitees = value) }
    }

    fun saveCalendarSettings() {
        viewModelScope.launch {
            _uiState.update { it.copy(isSavingCalendarSettings = true) }

            calendarSettingsRepository.updateSettings(
                targetCalendarId = _uiState.value.selectedCalendarId,
                defaultInvitees = _uiState.value.defaultInvitees.ifBlank { null }
            )

            _uiState.update { it.copy(isSavingCalendarSettings = false) }
        }
    }

    fun signOut(onSignOutComplete: () -> Unit) {
        viewModelScope.launch {
            _uiState.update { it.copy(isSigningOut = true) }
            authRepository.signOut()
            onSignOutComplete()
        }
    }

    fun getGmailAuthUrl(): String = backendApiClient.getGmailAuthUrl()

    fun getCalendarAuthUrl(): String = backendApiClient.getCalendarAuthUrl()

    fun clearError() {
        _uiState.update { it.copy(errorMessage = null) }
    }
}
