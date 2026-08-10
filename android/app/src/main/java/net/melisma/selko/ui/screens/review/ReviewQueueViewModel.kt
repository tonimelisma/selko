package net.melisma.selko.ui.screens.review

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import net.melisma.selko.R
import net.melisma.selko.data.api.BackendApiClient
import net.melisma.selko.data.model.CalendarEvent
import net.melisma.selko.data.model.Integration
import net.melisma.selko.data.model.IntegrationProvider
import net.melisma.selko.data.model.IntegrationStatus
import net.melisma.selko.data.model.SourceOrigin
import net.melisma.selko.data.repository.EventRepository
import net.melisma.selko.data.repository.EventResult
import net.melisma.selko.data.repository.IntegrationRepository
import net.melisma.selko.data.repository.IntegrationResult
import net.melisma.selko.data.repository.LiveUpdateRepository
import net.melisma.selko.data.repository.RepositoryResult
import net.melisma.selko.data.repository.SenderRuleRepository

data class SenderGroup(
    val senderName: String,
    val senderEmail: String,
    val events: List<CalendarEvent>
)

data class ReviewQueueUiState(
    val isLoading: Boolean = true,
    val integrations: List<Integration> = emptyList(),
    val events: List<CalendarEvent> = emptyList(),
    val senderGroups: List<SenderGroup> = emptyList(),
    val newSenderGroups: List<SenderGroup> = emptyList(),
    val changeSenderGroups: List<SenderGroup> = emptyList(),
    val errorMessage: String? = null,
    val isRefreshing: Boolean = false,
    val processingEventIds: Set<String> = emptySet(),
    val lastRejectedEvents: List<CalendarEvent> = emptyList(),
    val showUndoSnackbar: Boolean = false,
    val undoSnackbarMessage: String = ""
) {
    val isFirstRun: Boolean
        get() = integrations.isEmpty()

    val isEmailConnected: Boolean
        get() = integrations.any {
            it.provider in setOf(IntegrationProvider.GMAIL, IntegrationProvider.OUTLOOK) &&
                it.status == IntegrationStatus.ACTIVE
        }

    val isCalendarConnected: Boolean
        get() = integrations.any {
            it.provider == IntegrationProvider.GOOGLE_CALENDAR &&
                it.status == IntegrationStatus.ACTIVE
        }
}

class ReviewQueueViewModel(
    application: Application,
    private val eventRepository: EventRepository,
    private val integrationRepository: IntegrationRepository,
    private val backendApiClient: BackendApiClient,
    private val senderRuleRepository: SenderRuleRepository,
    private val liveUpdateRepository: LiveUpdateRepository? = null
) : AndroidViewModel(application) {

    private val _uiState = MutableStateFlow(ReviewQueueUiState())
    val uiState: StateFlow<ReviewQueueUiState> = _uiState.asStateFlow()

    private fun getString(resId: Int): String = getApplication<Application>().getString(resId)
    private fun getString(resId: Int, vararg args: Any): String = getApplication<Application>().getString(resId, *args)

    private var liveUpdateJob: Job? = null
    private var undoJob: Job? = null

    init {
        loadData()
    }

    fun startLiveUpdates() {
        val repo = liveUpdateRepository ?: return
        liveUpdateJob?.cancel()
        liveUpdateJob = viewModelScope.launch {
            repo.invalidations.collect { inv ->
                if (inv.resource in setOf("events", "event_sources", "integrations")) {
                    if (_uiState.value.processingEventIds.isEmpty()) {
                        checkIntegrations()
                    }
                }
            }
        }
    }

    fun stopLiveUpdates() {
        liveUpdateJob?.cancel()
        liveUpdateJob = null
    }

    fun onResume() {
        viewModelScope.launch {
            liveUpdateRepository?.refreshAll()
            checkIntegrations()
        }
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
                _uiState.update { it.copy(integrations = integrations) }

                if (integrations.isNotEmpty()) {
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
                val newEvents = events.filter { !it.isPendingChange }
                val changeEvents = events.filter { it.isPendingChange }
                val groups = groupBySender(events)
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        events = events,
                        senderGroups = groups,
                        newSenderGroups = groupBySender(newEvents),
                        changeSenderGroups = groupBySender(changeEvents)
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
            resolveSender(event)
        }.map { (senderInfo, groupEvents) ->
            SenderGroup(
                senderName = senderInfo.first,
                senderEmail = senderInfo.second,
                events = groupEvents
            )
        }
    }

    /** Prefer email authorship over calendar/photo provenance rows. */
    private fun resolveSender(event: CalendarEvent): Pair<String, String> {
        val sources = event.eventSources?.filter { !it.isUndone }.orEmpty()

        val emailSource = sources.firstOrNull { source ->
            source.sourceOrigin == SourceOrigin.EMAIL &&
                (source.emails?.fromEmail != null || source.emails?.fromName != null)
        }
        emailSource?.emails?.let { email ->
            val address = email.fromEmail ?: "unknown"
            val name = email.fromName ?: address
            return Pair(name, address)
        }

        if (sources.any { it.sourceOrigin == SourceOrigin.GOOGLE_PHOTOS }) {
            return Pair(getString(R.string.event_source_google_photos), "google_photos")
        }

        if (sources.any { it.sourceOrigin == SourceOrigin.GOOGLE_CALENDAR }) {
            return Pair(getString(R.string.settings_google_calendar), "google_calendar")
        }

        return Pair(
            getString(R.string.review_unknown_sender),
            "unknown"
        )
    }

    fun approveEvent(eventId: String) {
        if (!ensureCalendarConnected()) return
        viewModelScope.launch {
            _uiState.update { it.copy(processingEventIds = it.processingEventIds + eventId) }
            val event = _uiState.value.events.find { it.id == eventId }
            removeEventFromState(eventId)
            val ok = if (event?.isPendingChange == true) {
                backendApiClient.applyEventChange(eventId).isSuccess
            } else {
                eventRepository.approveEvent(eventId) is EventResult.Success
            }
            if (!ok) {
                if (event != null) {
                    _uiState.update { state ->
                        val updatedEvents = state.events + event
                        val newEvents = updatedEvents.filter { !it.isPendingChange }
                        val changeEvents = updatedEvents.filter { it.isPendingChange }
                        state.copy(
                            events = updatedEvents,
                            senderGroups = groupBySender(updatedEvents),
                            newSenderGroups = groupBySender(newEvents),
                            changeSenderGroups = groupBySender(changeEvents),
                            processingEventIds = state.processingEventIds - eventId,
                            errorMessage = getString(R.string.review_error_approve)
                        )
                    }
                } else {
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

    private fun removeEventFromState(eventId: String) {
        _uiState.update { state ->
            val updatedEvents = state.events.filter { it.id != eventId }
            val newEvents = updatedEvents.filter { !it.isPendingChange }
            val changeEvents = updatedEvents.filter { it.isPendingChange }
            state.copy(
                events = updatedEvents,
                senderGroups = groupBySender(updatedEvents),
                newSenderGroups = groupBySender(newEvents),
                changeSenderGroups = groupBySender(changeEvents),
                processingEventIds = state.processingEventIds - eventId
            )
        }
    }

    fun approveGroup(senderEmail: String) {
        if (!ensureCalendarConnected()) return
        viewModelScope.launch {
            val eventsToApprove = _uiState.value.senderGroups
                .find { it.senderEmail == senderEmail }
                ?.events ?: return@launch

            val eventIds = eventsToApprove.map { it.id }.toSet()
            _uiState.update { it.copy(processingEventIds = it.processingEventIds + eventIds) }

            var allSucceeded = true
            for (event in eventsToApprove) {
                val ok = if (event.isPendingChange) {
                    backendApiClient.applyEventChange(event.id).isSuccess
                } else {
                    eventRepository.approveEvent(event.id) is EventResult.Success
                }
                if (!ok) {
                    allSucceeded = false
                }
            }

            if (allSucceeded) {
                _uiState.update { state ->
                    val updatedEvents = state.events.filter { it.id !in eventIds }
                    val newEvents = updatedEvents.filter { !it.isPendingChange }
                    val changeEvents = updatedEvents.filter { it.isPendingChange }
                    state.copy(
                        events = updatedEvents,
                        senderGroups = groupBySender(updatedEvents),
                        newSenderGroups = groupBySender(newEvents),
                        changeSenderGroups = groupBySender(changeEvents),
                        processingEventIds = state.processingEventIds - eventIds
                    )
                }
            } else {
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

            val succeeded = mutableListOf<CalendarEvent>()
            var anyFailed = false
            for (event in eventsToReject) {
                val ok = if (event.isPendingChange) {
                    backendApiClient.rejectEventChange(event.id).isSuccess
                } else {
                    eventRepository.rejectEvent(event.id) is EventResult.Success
                }
                if (ok) {
                    succeeded.add(event)
                } else {
                    anyFailed = true
                }
            }

            if (succeeded.isNotEmpty() && !anyFailed) {
                _uiState.update { state ->
                    val updatedEvents = state.events.filter { it.id !in eventIds }
                    val newEvents = updatedEvents.filter { !it.isPendingChange }
                    val changeEvents = updatedEvents.filter { it.isPendingChange }
                    state.copy(
                        events = updatedEvents,
                        senderGroups = groupBySender(updatedEvents),
                        newSenderGroups = groupBySender(newEvents),
                        changeSenderGroups = groupBySender(changeEvents),
                        processingEventIds = state.processingEventIds - eventIds
                    )
                }
                showRejectUndo(succeeded)
            } else if (succeeded.isNotEmpty() && anyFailed) {
                // Partial success: remove succeeded, show undo for them, refresh for failed to get accurate state
                val succeededIds = succeeded.map { it.id }.toSet()
                _uiState.update { state ->
                    val updatedEvents = state.events.filter { it.id !in succeededIds }
                    val newEvents = updatedEvents.filter { !it.isPendingChange }
                    val changeEvents = updatedEvents.filter { it.isPendingChange }
                    state.copy(
                        events = updatedEvents,
                        senderGroups = groupBySender(updatedEvents),
                        newSenderGroups = groupBySender(newEvents),
                        changeSenderGroups = groupBySender(changeEvents),
                        processingEventIds = state.processingEventIds - eventIds
                    )
                }
                showRejectUndo(succeeded)
                fetchPendingEvents()
            } else {
                _uiState.update { it.copy(processingEventIds = it.processingEventIds - eventIds) }
                fetchPendingEvents()
            }
        }
    }

    fun rejectEvent(eventId: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(processingEventIds = it.processingEventIds + eventId) }
            val event = _uiState.value.events.find { it.id == eventId }
            val ok = if (event?.isPendingChange == true) {
                backendApiClient.rejectEventChange(eventId).isSuccess
            } else {
                eventRepository.rejectEvent(eventId) is EventResult.Success
            }
            if (ok) {
                removeEventFromState(eventId)
                if (event != null) {
                    showRejectUndo(listOf(event))
                }
            } else {
                _uiState.update {
                    it.copy(
                        processingEventIds = it.processingEventIds - eventId,
                        errorMessage = getString(R.string.review_error_reject)
                    )
                }
            }
        }
    }

    fun showRejectUndo(events: List<CalendarEvent>) {
        if (events.isEmpty()) return
        undoJob?.cancel()
        _uiState.update { state ->
            val combined = if (state.showUndoSnackbar) state.lastRejectedEvents + events else events
            val message = if (combined.size == 1) {
                getString(R.string.review_event_rejected)
            } else {
                getString(R.string.review_events_rejected, combined.size)
            }
            state.copy(
                lastRejectedEvents = combined,
                showUndoSnackbar = true,
                undoSnackbarMessage = message
            )
        }
        undoJob = viewModelScope.launch {
            delay(8000)
            dismissUndo()
        }
    }

    fun dismissUndo() {
        undoJob?.cancel()
        undoJob = null
        _uiState.update {
            it.copy(
                lastRejectedEvents = emptyList(),
                showUndoSnackbar = false,
                undoSnackbarMessage = ""
            )
        }
    }

    fun undoLastRejected() {
        val toUndo = _uiState.value.lastRejectedEvents
        if (toUndo.isEmpty()) return
        undoJob?.cancel()
        undoJob = null
        // Optimistically reinsert events
        _uiState.update { state ->
            val updatedEvents = state.events + toUndo
            val newEvents = updatedEvents.filter { !it.isPendingChange }
            val changeEvents = updatedEvents.filter { it.isPendingChange }
            state.copy(
                events = updatedEvents,
                senderGroups = groupBySender(updatedEvents),
                newSenderGroups = groupBySender(newEvents),
                changeSenderGroups = groupBySender(changeEvents),
                lastRejectedEvents = emptyList(),
                showUndoSnackbar = false,
                undoSnackbarMessage = ""
            )
        }
        viewModelScope.launch {
            var hadError = false
            for (event in toUndo) {
                val result = backendApiClient.undoHistoryEvent(event.id)
                if (result.isFailure) {
                    hadError = true
                    val msg = result.exceptionOrNull()?.message ?: getString(R.string.history_error_undo)
                    _uiState.update { state ->
                        val updatedEvents = state.events.filter { it.id != event.id }
                        val newEvents = updatedEvents.filter { !it.isPendingChange }
                        val changeEvents = updatedEvents.filter { it.isPendingChange }
                        state.copy(
                            events = updatedEvents,
                            senderGroups = groupBySender(updatedEvents),
                            newSenderGroups = groupBySender(newEvents),
                            changeSenderGroups = groupBySender(changeEvents),
                            errorMessage = msg
                        )
                    }
                }
            }
            fetchPendingEvents()
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
        if (!ensureCalendarConnected()) return
        viewModelScope.launch {
            when (senderRuleRepository.createRule(
                senderEmail = senderEmail,
                senderDomain = null,
                action = "auto_approve"
            )) {
                is RepositoryResult.Success -> {
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

    suspend fun startOAuth(provider: IntegrationProvider): Result<String> =
        backendApiClient.startOAuth(provider)

    private fun ensureCalendarConnected(): Boolean {
        if (_uiState.value.isCalendarConnected) return true
        _uiState.update {
            it.copy(errorMessage = getString(R.string.review_calendar_reconnect_required))
        }
        return false
    }

    fun clearError() {
        _uiState.update { it.copy(errorMessage = null) }
    }

    override fun onCleared() {
        super.onCleared()
        undoJob?.cancel()
        liveUpdateJob?.cancel()
    }
}
