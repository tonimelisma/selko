package net.melisma.selko.ui.screens.settings

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import net.melisma.selko.R
import net.melisma.selko.data.api.BackendApiClient
import net.melisma.selko.data.model.Integration
import net.melisma.selko.data.model.IntegrationProvider
import net.melisma.selko.data.model.IntegrationStatus
import net.melisma.selko.data.model.EmailFolderPreference
import net.melisma.selko.data.model.SenderRule
import net.melisma.selko.data.repository.AuthRepository
import net.melisma.selko.data.repository.CalendarSettings
import net.melisma.selko.data.repository.CalendarSettingsRepository
import net.melisma.selko.data.repository.IntegrationRepository
import net.melisma.selko.data.repository.EmailFolderRepository
import net.melisma.selko.data.repository.IntegrationResult
import net.melisma.selko.data.repository.RepositoryResult
import net.melisma.selko.data.repository.SenderRuleRepository

data class FolderUpdateFailure(val message: String, val requestedIncluded: Boolean)

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
    val isSavingCalendarSettings: Boolean = false,
    val rules: List<SenderRule> = emptyList(),
    val isLoadingRules: Boolean = false,
    val emailFolders: Map<IntegrationProvider, List<EmailFolderPreference>> = emptyMap(),
    val loadingFolderProviders: Set<IntegrationProvider> = emptySet(),
    val folderLoadErrors: Map<IntegrationProvider, String> = emptyMap(),
    val updatingFolderIds: Set<String> = emptySet(),
    val folderUpdateErrors: Map<String, FolderUpdateFailure> = emptyMap()
)

class SettingsViewModel(
    application: Application,
    private val authRepository: AuthRepository,
    private val integrationRepository: IntegrationRepository,
    private val calendarSettingsRepository: CalendarSettingsRepository,
    private val backendApiClient: BackendApiClient,
    private val senderRuleRepository: SenderRuleRepository,
    private val emailFolderRepository: EmailFolderRepository
) : AndroidViewModel(application) {

    private val _uiState = MutableStateFlow(SettingsUiState())
    val uiState: StateFlow<SettingsUiState> = _uiState.asStateFlow()

    private fun getString(resId: Int): String = getApplication<Application>().getString(resId)

    init {
        loadSettings()
        loadRules()
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
                    result.data.filter {
                        it.status == IntegrationStatus.ACTIVE &&
                            it.provider in setOf(IntegrationProvider.GMAIL, IntegrationProvider.OUTLOOK)
                    }.forEach { loadEmailFolders(it.provider) }
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
            when (val result = calendarSettingsRepository.getSettings()) {
                is RepositoryResult.Success -> {
                    val settings = result.data
                    _uiState.update {
                        it.copy(
                            calendarSettings = settings,
                            selectedCalendarId = settings?.targetCalendarId,
                            defaultInvitees = settings?.defaultInvitees ?: ""
                        )
                    }
                }
                is RepositoryResult.Error -> {
                    // Settings may not exist yet
                }
            }

            _uiState.update { it.copy(isLoading = false) }
        }
    }

    fun loadEmailFolders(provider: IntegrationProvider) {
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    loadingFolderProviders = it.loadingFolderProviders + provider,
                    folderLoadErrors = it.folderLoadErrors - provider
                )
            }
            when (val result = emailFolderRepository.list(provider)) {
                is RepositoryResult.Success -> _uiState.update {
                    it.copy(
                        emailFolders = it.emailFolders + (provider to result.data),
                        loadingFolderProviders = it.loadingFolderProviders - provider
                    )
                }
                is RepositoryResult.Error -> _uiState.update {
                    it.copy(
                        loadingFolderProviders = it.loadingFolderProviders - provider,
                        folderLoadErrors = it.folderLoadErrors + (provider to result.message)
                    )
                }
            }
        }
    }

    fun updateEmailFolder(provider: IntegrationProvider, folderId: String, isIncluded: Boolean) {
        val previous = _uiState.value.emailFolders[provider]?.firstOrNull { it.id == folderId } ?: return
        if (folderId in _uiState.value.updatingFolderIds) return
        val optimistic = previous.copy(isIncluded = isIncluded)
        replaceFolder(provider, optimistic)
        _uiState.update {
            it.copy(
                updatingFolderIds = it.updatingFolderIds + folderId,
                folderUpdateErrors = it.folderUpdateErrors - folderId
            )
        }
        viewModelScope.launch {
            when (val result = emailFolderRepository.update(provider, folderId, isIncluded)) {
                is RepositoryResult.Success -> replaceFolder(provider, result.data)
                is RepositoryResult.Error -> {
                    replaceFolder(provider, previous)
                    _uiState.update {
                        it.copy(folderUpdateErrors = it.folderUpdateErrors + (
                            folderId to FolderUpdateFailure(result.message, isIncluded)
                        ))
                    }
                }
            }
            _uiState.update { it.copy(updatingFolderIds = it.updatingFolderIds - folderId) }
        }
    }

    fun retryEmailFolder(provider: IntegrationProvider, folderId: String) {
        val failure = _uiState.value.folderUpdateErrors[folderId] ?: return
        updateEmailFolder(provider, folderId, failure.requestedIncluded)
    }

    private fun replaceFolder(provider: IntegrationProvider, folder: EmailFolderPreference) {
        _uiState.update { state ->
            val folders = state.emailFolders[provider].orEmpty().map { if (it.id == folder.id) folder else it }
            state.copy(emailFolders = state.emailFolders + (provider to folders))
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
                            errorMessage = getString(R.string.settings_error_disconnect)
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

            when (calendarSettingsRepository.updateSettings(
                targetCalendarId = _uiState.value.selectedCalendarId,
                defaultInvitees = _uiState.value.defaultInvitees.ifBlank { null }
            )) {
                is RepositoryResult.Success -> {
                    _uiState.update { it.copy(isSavingCalendarSettings = false) }
                }
                is RepositoryResult.Error -> {
                    _uiState.update {
                        it.copy(
                            isSavingCalendarSettings = false,
                            errorMessage = getString(R.string.settings_error_save_calendar)
                        )
                    }
                }
            }
        }
    }

    fun signOut(onSignOutComplete: () -> Unit) {
        viewModelScope.launch {
            _uiState.update { it.copy(isSigningOut = true) }
            authRepository.signOut()
            onSignOutComplete()
        }
    }

    fun loadRules() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoadingRules = true) }
            when (val result = senderRuleRepository.fetchRules()) {
                is RepositoryResult.Success -> {
                    _uiState.update { it.copy(rules = result.data, isLoadingRules = false) }
                }
                is RepositoryResult.Error -> {
                    _uiState.update {
                        it.copy(
                            isLoadingRules = false,
                            errorMessage = getString(R.string.settings_error_load_rules)
                        )
                    }
                }
            }
        }
    }

    fun createRule(senderEmail: String?, senderDomain: String?, action: String) {
        viewModelScope.launch {
            when (senderRuleRepository.createRule(senderEmail, senderDomain, action)) {
                is RepositoryResult.Success -> loadRules()
                is RepositoryResult.Error -> {
                    _uiState.update { it.copy(errorMessage = getString(R.string.settings_error_create_rule)) }
                }
            }
        }
    }

    fun deleteRule(id: String) {
        viewModelScope.launch {
            when (senderRuleRepository.deleteRule(id)) {
                is RepositoryResult.Success -> loadRules()
                is RepositoryResult.Error -> {
                    _uiState.update { it.copy(errorMessage = getString(R.string.settings_error_delete_rule)) }
                }
            }
        }
    }

    fun getGmailAuthUrl(): String = backendApiClient.getGmailAuthUrl()

    fun getOutlookAuthUrl(): String = backendApiClient.getOutlookAuthUrl()

    fun getCalendarAuthUrl(): String = backendApiClient.getCalendarAuthUrl()

    fun clearError() {
        _uiState.update { it.copy(errorMessage = null) }
    }
}
