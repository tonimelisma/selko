package net.melisma.selko.ui.screens.history

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.datetime.TimeZone
import kotlinx.datetime.toLocalDateTime
import net.melisma.selko.data.model.CalendarEvent
import net.melisma.selko.data.model.EventStatus
import net.melisma.selko.data.repository.EventRepository
import net.melisma.selko.data.repository.EventResult
import net.melisma.selko.data.repository.IntegrationRepository

data class DateGroup(
    val dateLabel: String,
    val events: List<CalendarEvent>
)

data class HistoryUiState(
    val isLoading: Boolean = true,
    val dateGroups: List<DateGroup> = emptyList(),
    val allEvents: List<CalendarEvent> = emptyList(),
    val errorMessage: String? = null,
    val isLoadingMore: Boolean = false,
    val hasMore: Boolean = true,
    val processingEventIds: Set<String> = emptySet()
)

class HistoryViewModel(
    private val eventRepository: EventRepository,
    private val integrationRepository: IntegrationRepository
) : ViewModel() {

    private val _uiState = MutableStateFlow(HistoryUiState())
    val uiState: StateFlow<HistoryUiState> = _uiState.asStateFlow()

    private val pageSize = 20
    private var currentOffset = 0

    init {
        loadHistory()
    }

    fun loadHistory() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, errorMessage = null) }
            currentOffset = 0
            fetchEvents(isInitial = true)
        }
    }

    fun loadMore() {
        if (_uiState.value.isLoadingMore || !_uiState.value.hasMore) return

        viewModelScope.launch {
            _uiState.update { it.copy(isLoadingMore = true) }
            fetchEvents(isInitial = false)
        }
    }

    private suspend fun fetchEvents(isInitial: Boolean) {
        when (val result = eventRepository.fetchActivityEvents(
            limit = pageSize,
            offset = currentOffset
        )) {
            is EventResult.Success -> {
                val newEvents = result.data
                val allEvents = if (isInitial) newEvents
                    else _uiState.value.allEvents + newEvents
                val groups = groupByDate(allEvents)

                currentOffset += newEvents.size

                _uiState.update {
                    it.copy(
                        isLoading = false,
                        isLoadingMore = false,
                        allEvents = allEvents,
                        dateGroups = groups,
                        hasMore = newEvents.size >= pageSize
                    )
                }
            }
            is EventResult.Error -> {
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        isLoadingMore = false,
                        errorMessage = result.message
                    )
                }
            }
        }
    }

    private fun groupByDate(events: List<CalendarEvent>): List<DateGroup> {
        val tz = TimeZone.currentSystemDefault()
        return events.groupBy { event ->
            val date = (event.updatedAt ?: event.createdAt)
                ?.toLocalDateTime(tz)
                ?.date
            date?.let {
                "${it.dayOfMonth} ${it.month.name.lowercase().replaceFirstChar { c -> c.uppercase() }} ${it.year}"
            } ?: "Unknown Date"
        }.map { (dateLabel, groupEvents) ->
            DateGroup(dateLabel = dateLabel, events = groupEvents)
        }
    }

    fun undoEvent(eventId: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(processingEventIds = it.processingEventIds + eventId) }

            when (eventRepository.updateEventStatus(eventId, EventStatus.PENDING_REVIEW)) {
                is EventResult.Success -> {
                    _uiState.update { state ->
                        val updatedEvents = state.allEvents.filter { it.id != eventId }
                        state.copy(
                            allEvents = updatedEvents,
                            dateGroups = groupByDate(updatedEvents),
                            processingEventIds = state.processingEventIds - eventId
                        )
                    }
                }
                is EventResult.Error -> {
                    _uiState.update {
                        it.copy(
                            processingEventIds = it.processingEventIds - eventId,
                            errorMessage = "Failed to undo action"
                        )
                    }
                }
            }
        }
    }

    fun retrySync(eventId: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(processingEventIds = it.processingEventIds + eventId) }

            when (eventRepository.updateEventStatus(eventId, EventStatus.APPROVED)) {
                is EventResult.Success -> {
                    // Refresh to get updated state
                    _uiState.update { it.copy(processingEventIds = it.processingEventIds - eventId) }
                    loadHistory()
                }
                is EventResult.Error -> {
                    _uiState.update {
                        it.copy(
                            processingEventIds = it.processingEventIds - eventId,
                            errorMessage = "Failed to retry sync"
                        )
                    }
                }
            }
        }
    }

    fun clearError() {
        _uiState.update { it.copy(errorMessage = null) }
    }
}
