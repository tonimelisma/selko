package net.melisma.selko.ui.screens.review

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.datetime.Instant
import net.melisma.selko.data.model.CalendarEvent
import net.melisma.selko.data.model.Email
import net.melisma.selko.data.model.EventSource
import net.melisma.selko.data.repository.EventRepository
import net.melisma.selko.data.repository.EventResult

data class EventDetailUiState(
    val isLoading: Boolean = true,
    val event: CalendarEvent? = null,
    val sources: List<EventSource> = emptyList(),
    val sourceEmail: Email? = null,
    val title: String = "",
    val startDatetime: String = "",
    val endDatetime: String = "",
    val location: String = "",
    val description: String = "",
    val allDay: Boolean = false,
    val isSaving: Boolean = false,
    val isApproving: Boolean = false,
    val isRejecting: Boolean = false,
    val errorMessage: String? = null,
    val isDone: Boolean = false,
    val hasUnsavedChanges: Boolean = false
)

class EventDetailViewModel(
    private val eventRepository: EventRepository,
    private val eventId: String
) : ViewModel() {

    private val _uiState = MutableStateFlow(EventDetailUiState())
    val uiState: StateFlow<EventDetailUiState> = _uiState.asStateFlow()

    init {
        loadEvent()
    }

    private fun loadEvent() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, errorMessage = null) }

            when (val result = eventRepository.getEventWithSources(eventId)) {
                is EventResult.Success -> {
                    val event = result.data
                    val sources = event.eventSources ?: emptyList()
                    val sourceEmail = sources.firstOrNull()?.emails

                    _uiState.update {
                        it.copy(
                            isLoading = false,
                            event = event,
                            sources = sources,
                            sourceEmail = sourceEmail,
                            title = event.title,
                            startDatetime = event.startDatetime?.toString() ?: "",
                            endDatetime = event.endDatetime?.toString() ?: "",
                            location = event.location ?: "",
                            description = event.description ?: "",
                            allDay = event.allDay
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
    }

    fun onTitleChange(value: String) {
        _uiState.update { it.copy(title = value, hasUnsavedChanges = true) }
    }

    fun onLocationChange(value: String) {
        _uiState.update { it.copy(location = value, hasUnsavedChanges = true) }
    }

    fun onDescriptionChange(value: String) {
        _uiState.update { it.copy(description = value, hasUnsavedChanges = true) }
    }

    fun onStartDatetimeChange(value: String) {
        _uiState.update { it.copy(startDatetime = value, hasUnsavedChanges = true) }
    }

    fun onEndDatetimeChange(value: String) {
        _uiState.update { it.copy(endDatetime = value, hasUnsavedChanges = true) }
    }

    fun onAllDayChange(value: Boolean) {
        _uiState.update { it.copy(allDay = value, hasUnsavedChanges = true) }
    }

    fun saveChanges() {
        val state = _uiState.value
        if (!state.hasUnsavedChanges) return

        viewModelScope.launch {
            _uiState.update { it.copy(isSaving = true) }

            val startInstant = try {
                Instant.parse(state.startDatetime)
            } catch (e: Exception) {
                null
            }

            val endInstant = try {
                Instant.parse(state.endDatetime)
            } catch (e: Exception) {
                null
            }

            when (val result = eventRepository.updateEvent(
                eventId = eventId,
                title = state.title,
                startDatetime = startInstant,
                endDatetime = endInstant,
                location = state.location.ifBlank { null },
                description = state.description.ifBlank { null },
                allDay = state.allDay
            )) {
                is EventResult.Success -> {
                    _uiState.update {
                        it.copy(
                            isSaving = false,
                            event = result.data,
                            hasUnsavedChanges = false
                        )
                    }
                }
                is EventResult.Error -> {
                    _uiState.update {
                        it.copy(
                            isSaving = false,
                            errorMessage = result.message
                        )
                    }
                }
            }
        }
    }

    fun approveEvent() {
        viewModelScope.launch {
            _uiState.update { it.copy(isApproving = true) }

            // Save any pending changes first
            if (_uiState.value.hasUnsavedChanges) {
                saveChangesSync()
            }

            when (eventRepository.approveEvent(eventId)) {
                is EventResult.Success -> {
                    _uiState.update { it.copy(isApproving = false, isDone = true) }
                }
                is EventResult.Error -> {
                    _uiState.update {
                        it.copy(
                            isApproving = false,
                            errorMessage = "Failed to approve event"
                        )
                    }
                }
            }
        }
    }

    fun rejectEvent() {
        viewModelScope.launch {
            _uiState.update { it.copy(isRejecting = true) }

            when (eventRepository.rejectEvent(eventId)) {
                is EventResult.Success -> {
                    _uiState.update { it.copy(isRejecting = false, isDone = true) }
                }
                is EventResult.Error -> {
                    _uiState.update {
                        it.copy(
                            isRejecting = false,
                            errorMessage = "Failed to reject event"
                        )
                    }
                }
            }
        }
    }

    private suspend fun saveChangesSync() {
        val state = _uiState.value

        val startInstant = try {
            Instant.parse(state.startDatetime)
        } catch (e: Exception) {
            null
        }

        val endInstant = try {
            Instant.parse(state.endDatetime)
        } catch (e: Exception) {
            null
        }

        eventRepository.updateEvent(
            eventId = eventId,
            title = state.title,
            startDatetime = startInstant,
            endDatetime = endInstant,
            location = state.location.ifBlank { null },
            description = state.description.ifBlank { null },
            allDay = state.allDay
        )
    }

    fun clearError() {
        _uiState.update { it.copy(errorMessage = null) }
    }
}
