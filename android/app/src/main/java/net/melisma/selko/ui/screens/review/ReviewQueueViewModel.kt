package net.melisma.selko.ui.screens.review

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import net.melisma.selko.data.api.BackendApiClient
import kotlinx.datetime.Instant
import net.melisma.selko.data.model.CalendarEvent
import net.melisma.selko.data.model.IntegrationProvider
import net.melisma.selko.data.model.IntegrationStatus
import net.melisma.selko.data.repository.EventRepository
import net.melisma.selko.data.repository.EventResult
import net.melisma.selko.data.repository.IntegrationRepository
import net.melisma.selko.data.repository.IntegrationResult

data class EmailGroup(
    val emailId: String,
    val subject: String,
    val dateSent: Instant?,
    val events: List<CalendarEvent>
)

data class SenderGroup(
    val senderName: String,
    val senderEmail: String,
    val emailGroups: List<EmailGroup>
) {
    val allEvents: List<CalendarEvent> get() = emailGroups.flatMap { it.events }
}

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
    private val eventRepository: EventRepository,
    private val integrationRepository: IntegrationRepository,
    private val backendApiClient: BackendApiClient
) : ViewModel() {

    private val _uiState = MutableStateFlow(ReviewQueueUiState())
    val uiState: StateFlow<ReviewQueueUiState> = _uiState.asStateFlow()

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
            Pair(email?.fromName ?: email?.fromEmail ?: "Unknown", email?.fromEmail ?: "unknown")
        }.map { (senderInfo, groupEvents) ->
            // Sub-group by email ID
            val emailGroups = groupEvents.groupBy { event ->
                event.eventSources?.firstOrNull()?.emailId ?: "unknown"
            }.map { (emailId, emailEvents) ->
                val sourceEmail = emailEvents.firstOrNull()?.eventSources?.firstOrNull()?.emails
                EmailGroup(
                    emailId = emailId,
                    subject = sourceEmail?.subject ?: "No subject",
                    dateSent = sourceEmail?.dateSent,
                    events = emailEvents
                )
            }
            SenderGroup(
                senderName = senderInfo.first,
                senderEmail = senderInfo.second,
                emailGroups = emailGroups
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
                            errorMessage = "Failed to approve event"
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
                ?.allEvents ?: return@launch

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

    fun approveEmailGroup(emailId: String) {
        viewModelScope.launch {
            val eventsToApprove = _uiState.value.senderGroups
                .flatMap { it.emailGroups }
                .find { it.emailId == emailId }
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
                            errorMessage = "Failed to reject event"
                        )
                    }
                }
            }
        }
    }

    fun getGmailAuthUrl(): String = backendApiClient.getGmailAuthUrl()

    fun clearError() {
        _uiState.update { it.copy(errorMessage = null) }
    }
}
