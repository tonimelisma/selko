package net.melisma.selko.ui.screens.review

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
import net.melisma.selko.data.model.CalendarEvent
import net.melisma.selko.data.model.IntegrationProvider
import net.melisma.selko.data.model.IntegrationStatus
import net.melisma.selko.data.repository.EventRepository
import net.melisma.selko.data.repository.EventResult
import net.melisma.selko.data.repository.IntegrationRepository
import net.melisma.selko.data.repository.IntegrationResult
import net.melisma.selko.data.repository.RepositoryResult
import net.melisma.selko.data.repository.SenderRuleRepository

data class SenderGroup(
    val senderName: String,
    val senderEmail: String,
    val events: List<CalendarEvent>
)

data class ReviewQueueUiState(
    val isLoading: Boolean = true,
    val isGmailConnected: Boolean = false,
    val isCalendarConnected: Boolean = false,
    val events: List<CalendarEvent> = emptyList(),
    val senderGroups: List<SenderGroup> = emptyList(),
    val errorMessage: String? = null,
    val isRefreshing: Boolean = false,
    val processingEventIds: Set<String> = emptySet()
)

class ReviewQueueViewModel(
    application: Application,
    private val eventRepository: EventRepository,
    private val integrationRepository: IntegrationRepository,
    private val backendApiClient: BackendApiClient,
    private val senderRuleRepository: SenderRuleRepository
) : AndroidViewModel(application) {

    private val _uiState = MutableStateFlow(ReviewQueueUiState())
    val uiState: StateFlow<ReviewQueueUiState> = _uiState.asStateFlow()

    private fun getString(resId: Int): String = getApplication<Application>().getString(resId)

    init {
        loadData()
    }

    fun loadData() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, errorMessage = null) }
            checkIntegrations()
        }
    }

    fun refresh() {
        viewModelScope.launch {
            _uiState.update { it.copy(isRefreshing = true, errorMessage = null) }
            checkIntegrations()
            _uiState.update { it.copy(isRefreshing = false) }
        }
    }

    private suspend fun checkIntegrations() {
        val integrationsResult = integrationRepository.fetchIntegrations()
        when (integrationsResult) {
            is IntegrationResult.Success -> {
                val integrations = integrationsResult.data
                val gmailConnected = integrations.any {
                    it.provider == IntegrationProvider.GMAIL && it.status == IntegrationStatus.ACTIVE
                }
                val calendarConnected = integrations.any {
                    it.provider == IntegrationProvider.GOOGLE_CALENDAR && it.status == IntegrationStatus.ACTIVE
                }
                _uiState.update {
                    it.copy(
                        isGmailConnected = gmailConnected,
                        isCalendarConnected = calendarConnected
                    )
                }

                if (gmailConnected && calendarConnected) {
                    fetchPendingEvents()
                } else {
                    _uiState.update { it.copy(isLoading = false) }
                }
            }
            is IntegrationResult.Error -> {
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        errorMessage = integrationsResult.message
                    )
                }
            }
        }
    }

    private suspend fun fetchPendingEvents() {
        when (val result = eventRepository.fetchPendingEventsWithSources()) {
            is EventResult.Success -> {
                val events = result.data
                val groups = groupBySender(events)
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        events = events,
                        senderGroups = groups
                    )
                }
            }
            is EventResult.Error -> {
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        errorMessage = result.message
                    )
                }
            }
        }
    }

    private fun groupBySender(events: List<CalendarEvent>): List<SenderGroup> {
        return events.groupBy { event ->
            val source = event.eventSources?.firstOrNull()
            val email = source?.emails
            Pair(email?.fromName ?: email?.fromEmail ?: getString(R.string.review_unknown_sender), email?.fromEmail ?: "unknown")
        }.map { (senderInfo, groupEvents) ->
            SenderGroup(
                senderName = senderInfo.first,
                senderEmail = senderInfo.second,
                events = groupEvents
            )
        }
    }

    fun approveEvent(eventId: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(processingEventIds = it.processingEventIds + eventId) }
            when (eventRepository.approveEvent(eventId)) {
                is EventResult.Success -> {
                    _uiState.update { state ->
                        val updatedEvents = state.events.filter { it.id != eventId }
                        state.copy(
                            events = updatedEvents,
                            senderGroups = groupBySender(updatedEvents),
                            processingEventIds = state.processingEventIds - eventId
                        )
                    }
                }
                is EventResult.Error -> {
                    _uiState.update {
                        it.copy(
                            processingEventIds = it.processingEventIds - eventId,
                            errorMessage = getString(R.string.review_error_approve)
                        )
                    }
                }
            }
        }
    }

    fun approveGroup(senderEmail: String) {
        viewModelScope.launch {
            val eventsToApprove = _uiState.value.senderGroups
                .find { it.senderEmail == senderEmail }
                ?.events ?: return@launch

            val eventIds = eventsToApprove.map { it.id }.toSet()
            _uiState.update { it.copy(processingEventIds = it.processingEventIds + eventIds) }

            var allSucceeded = true
            for (event in eventsToApprove) {
                when (eventRepository.approveEvent(event.id)) {
                    is EventResult.Success -> { /* continue */ }
                    is EventResult.Error -> { allSucceeded = false }
                }
            }

            if (allSucceeded) {
                _uiState.update { state ->
                    val updatedEvents = state.events.filter { it.id !in eventIds }
                    state.copy(
                        events = updatedEvents,
                        senderGroups = groupBySender(updatedEvents),
                        processingEventIds = state.processingEventIds - eventIds
                    )
                }
            } else {
                // Refresh to get accurate state
                _uiState.update { it.copy(processingEventIds = it.processingEventIds - eventIds) }
                fetchPendingEvents()
            }
        }
    }

    fun rejectGroup(senderEmail: String) {
        viewModelScope.launch {
            val eventsToReject = _uiState.value.senderGroups
                .find { it.senderEmail == senderEmail }
                ?.events ?: return@launch

            val eventIds = eventsToReject.map { it.id }.toSet()
            _uiState.update { it.copy(processingEventIds = it.processingEventIds + eventIds) }

            var allSucceeded = true
            for (event in eventsToReject) {
                when (eventRepository.rejectEvent(event.id)) {
                    is EventResult.Success -> { /* continue */ }
                    is EventResult.Error -> { allSucceeded = false }
                }
            }

            if (allSucceeded) {
                _uiState.update { state ->
                    val updatedEvents = state.events.filter { it.id !in eventIds }
                    state.copy(
                        events = updatedEvents,
                        senderGroups = groupBySender(updatedEvents),
                        processingEventIds = state.processingEventIds - eventIds
                    )
                }
            } else {
                _uiState.update { it.copy(processingEventIds = it.processingEventIds - eventIds) }
                fetchPendingEvents()
            }
        }
    }

    fun rejectEvent(eventId: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(processingEventIds = it.processingEventIds + eventId) }
            when (eventRepository.rejectEvent(eventId)) {
                is EventResult.Success -> {
                    _uiState.update { state ->
                        val updatedEvents = state.events.filter { it.id != eventId }
                        state.copy(
                            events = updatedEvents,
                            senderGroups = groupBySender(updatedEvents),
                            processingEventIds = state.processingEventIds - eventId
                        )
                    }
                }
                is EventResult.Error -> {
                    _uiState.update {
                        it.copy(
                            processingEventIds = it.processingEventIds - eventId,
                            errorMessage = getString(R.string.review_error_reject)
                        )
                    }
                }
            }
        }
    }

    fun ignoreSender(senderEmail: String) {
        viewModelScope.launch {
            when (senderRuleRepository.createRule(
                senderEmail = senderEmail,
                senderDomain = null,
                action = "ignore"
            )) {
                is RepositoryResult.Success -> {
                    // Reject all events from this sender
                    val eventsToReject = _uiState.value.senderGroups
                        .find { it.senderEmail == senderEmail }
                        ?.events ?: return@launch

                    val eventIds = eventsToReject.map { it.id }.toSet()
                    _uiState.update { it.copy(processingEventIds = it.processingEventIds + eventIds) }

                    for (event in eventsToReject) {
                        eventRepository.rejectEvent(event.id)
                    }

                    _uiState.update { state ->
                        val updatedEvents = state.events.filter { it.id !in eventIds }
                        state.copy(
                            events = updatedEvents,
                            senderGroups = groupBySender(updatedEvents),
                            processingEventIds = state.processingEventIds - eventIds
                        )
                    }
                }
                is RepositoryResult.Error -> {
                    _uiState.update { it.copy(errorMessage = getString(R.string.review_error_ignore_rule)) }
                }
            }
        }
    }

    fun autoApproveSender(senderEmail: String) {
        viewModelScope.launch {
            when (senderRuleRepository.createRule(
                senderEmail = senderEmail,
                senderDomain = null,
                action = "auto_approve"
            )) {
                is RepositoryResult.Success -> {
                    // Approve all events from this sender
                    val eventsToApprove = _uiState.value.senderGroups
                        .find { it.senderEmail == senderEmail }
                        ?.events ?: return@launch

                    val eventIds = eventsToApprove.map { it.id }.toSet()
                    _uiState.update { it.copy(processingEventIds = it.processingEventIds + eventIds) }

                    for (event in eventsToApprove) {
                        eventRepository.approveEvent(event.id)
                    }

                    _uiState.update { state ->
                        val updatedEvents = state.events.filter { it.id !in eventIds }
                        state.copy(
                            events = updatedEvents,
                            senderGroups = groupBySender(updatedEvents),
                            processingEventIds = state.processingEventIds - eventIds
                        )
                    }
                }
                is RepositoryResult.Error -> {
                    _uiState.update { it.copy(errorMessage = getString(R.string.review_error_auto_approve_rule)) }
                }
            }
        }
    }

    fun getGmailAuthUrl(): String = backendApiClient.getGmailAuthUrl()

    fun clearError() {
        _uiState.update { it.copy(errorMessage = null) }
    }
}
