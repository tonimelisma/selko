package net.melisma.selko.ui.screens.review

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.datetime.Instant
import kotlinx.datetime.LocalDateTime
import kotlinx.datetime.LocalTime
import kotlinx.datetime.TimeZone
import kotlinx.datetime.toInstant
import kotlinx.datetime.toLocalDateTime
import net.melisma.selko.R
import net.melisma.selko.data.model.CalendarEvent
import net.melisma.selko.data.model.Email
import net.melisma.selko.data.model.EventSource
import net.melisma.selko.data.model.SourceOrigin
import net.melisma.selko.data.repository.EventRepository
import net.melisma.selko.data.repository.EventResult

data class EventDetailUiState(
    val isLoading: Boolean = true,
    val event: CalendarEvent? = null,
    val sources: List<EventSource> = emptyList(),
    val sourceEmail: Email? = null,
    val sourceOrigin: SourceOrigin = SourceOrigin.EMAIL,
    val title: String = "",
    val startInstant: Instant? = null,
    val endInstant: Instant? = null,
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
    application: Application,
    private val eventRepository: EventRepository,
    private val eventId: String
) : AndroidViewModel(application) {

    private val _uiState = MutableStateFlow(EventDetailUiState())
    val uiState: StateFlow<EventDetailUiState> = _uiState.asStateFlow()

    private fun getString(resId: Int): String = getApplication<Application>().getString(resId)

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
                    val firstSource = sources.firstOrNull()
                    val sourceEmail = firstSource?.emails
                    val sourceOrigin = firstSource?.sourceOrigin ?: SourceOrigin.EMAIL

                    _uiState.update {
                        it.copy(
                            isLoading = false,
                            event = event,
                            sources = sources,
                            sourceEmail = sourceEmail,
                            sourceOrigin = sourceOrigin,
                            title = event.title,
                            startInstant = event.startDatetime,
                            endInstant = event.endDatetime,
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

    fun onStartDateChange(millis: Long) {
        val current = _uiState.value.startInstant
        val tz = TimeZone.currentSystemDefault()
        val selectedDate = Instant.fromEpochMilliseconds(millis).toLocalDateTime(tz).date
        val currentTime = current?.toLocalDateTime(tz)?.time ?: LocalTime(9, 0)
        val newInstant = LocalDateTime(selectedDate, currentTime).toInstant(tz)
        _uiState.update { it.copy(startInstant = newInstant, hasUnsavedChanges = true) }
    }

    fun onStartTimeChange(hour: Int, minute: Int) {
        val current = _uiState.value.startInstant ?: return
        val tz = TimeZone.currentSystemDefault()
        val currentDate = current.toLocalDateTime(tz).date
        val newInstant = LocalDateTime(currentDate, LocalTime(hour, minute)).toInstant(tz)
        _uiState.update { it.copy(startInstant = newInstant, hasUnsavedChanges = true) }
    }

    fun onEndDateChange(millis: Long) {
        val current = _uiState.value.endInstant
        val tz = TimeZone.currentSystemDefault()
        val selectedDate = Instant.fromEpochMilliseconds(millis).toLocalDateTime(tz).date
        val currentTime = current?.toLocalDateTime(tz)?.time ?: LocalTime(10, 0)
        val newInstant = LocalDateTime(selectedDate, currentTime).toInstant(tz)
        _uiState.update { it.copy(endInstant = newInstant, hasUnsavedChanges = true) }
    }

    fun onEndTimeChange(hour: Int, minute: Int) {
        val current = _uiState.value.endInstant ?: return
        val tz = TimeZone.currentSystemDefault()
        val currentDate = current.toLocalDateTime(tz).date
        val newInstant = LocalDateTime(currentDate, LocalTime(hour, minute)).toInstant(tz)
        _uiState.update { it.copy(endInstant = newInstant, hasUnsavedChanges = true) }
    }

    fun onAllDayChange(value: Boolean) {
        _uiState.update { it.copy(allDay = value, hasUnsavedChanges = true) }
    }

    fun saveChanges() {
        val state = _uiState.value
        if (!state.hasUnsavedChanges) return

        viewModelScope.launch {
            _uiState.update { it.copy(isSaving = true) }

            val startInstant = state.startInstant
            val endInstant = state.endInstant

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
                val saved = saveChangesSync()
                if (!saved) {
                    _uiState.update {
                        it.copy(
                            isApproving = false,
                            errorMessage = getString(R.string.event_detail_error_save)
                        )
                    }
                    return@launch
                }
            }

            when (eventRepository.approveEvent(eventId)) {
                is EventResult.Success -> {
                    _uiState.update { it.copy(isApproving = false, isDone = true) }
                }
                is EventResult.Error -> {
                    _uiState.update {
                        it.copy(
                            isApproving = false,
                            errorMessage = getString(R.string.event_detail_error_approve)
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
                            errorMessage = getString(R.string.event_detail_error_reject)
                        )
                    }
                }
            }
        }
    }

    private suspend fun saveChangesSync(): Boolean {
        val state = _uiState.value

        val startInstant = state.startInstant
        val endInstant = state.endInstant

        return when (eventRepository.updateEvent(
            eventId = eventId,
            title = state.title,
            startDatetime = startInstant,
            endDatetime = endInstant,
            location = state.location.ifBlank { null },
            description = state.description.ifBlank { null },
            allDay = state.allDay
        )) {
            is EventResult.Success -> true
            is EventResult.Error -> false
        }
    }

    fun clearError() {
        _uiState.update { it.copy(errorMessage = null) }
    }
}
