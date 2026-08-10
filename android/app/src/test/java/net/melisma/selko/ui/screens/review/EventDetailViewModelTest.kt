package net.melisma.selko.ui.screens.review

import android.app.Application
import app.cash.turbine.test
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.mockk
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import net.melisma.selko.R
import net.melisma.selko.data.api.BackendApiClient
import net.melisma.selko.data.model.CalendarEvent
import net.melisma.selko.data.model.Email
import net.melisma.selko.data.model.EventSource
import net.melisma.selko.data.model.EventStatus
import net.melisma.selko.data.model.SourceOrigin
import net.melisma.selko.data.model.SourceType
import net.melisma.selko.data.model.Integration
import net.melisma.selko.data.model.IntegrationProvider
import net.melisma.selko.data.model.IntegrationStatus
import net.melisma.selko.data.repository.EventRepository
import net.melisma.selko.data.repository.EventResult
import net.melisma.selko.data.repository.IntegrationRepository
import net.melisma.selko.data.repository.IntegrationResult
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class EventDetailViewModelTest {

    private lateinit var application: Application
    private lateinit var eventRepository: EventRepository
    private lateinit var integrationRepository: IntegrationRepository
    private lateinit var backendApiClient: BackendApiClient
    private val testDispatcher = StandardTestDispatcher()

    private val testEmail = Email(
        id = "email-1",
        userId = "user-1",
        subject = "Test Event Email",
        fromEmail = "sender@example.com",
        fromName = "Test Sender"
    )

    @Before
    fun setup() {
        Dispatchers.setMain(testDispatcher)
        application = mockk(relaxed = true)
        every { application.getString(R.string.event_detail_error_approve) } returns "Failed to approve event"
        every { application.getString(R.string.event_detail_error_reject) } returns "Failed to reject event"
        every { application.getString(R.string.review_event_rejected) } returns "Event rejected"
        every { application.getString(R.string.event_detail_error_save) } returns "Failed to save changes. Please try again."
        every {
            application.getString(R.string.review_calendar_reconnect_required)
        } returns "Reconnect Google Calendar to accept suggestions."
        eventRepository = mockk(relaxed = true)
        integrationRepository = mockk(relaxed = true)
        backendApiClient = mockk(relaxed = true)
        coEvery { integrationRepository.fetchIntegrations() } returns IntegrationResult.Success(
            listOf(
                Integration(
                    id = "calendar",
                    userId = "user-1",
                    provider = IntegrationProvider.GOOGLE_CALENDAR,
                    status = IntegrationStatus.ACTIVE
                )
            )
        )
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun createViewModel(eventId: String): EventDetailViewModel {
        return EventDetailViewModel(
            application,
            eventRepository,
            integrationRepository,
            backendApiClient,
            eventId
        )
    }

    @Test
    fun `loads event with email source origin`() = runTest {
        val emailSource = EventSource(
            id = "source-1",
            eventId = "event-1",
            emailId = "email-1",
            sourceOrigin = SourceOrigin.EMAIL,
            sourceType = SourceType.NEW_INVITATION,
            emails = testEmail
        )
        val event = CalendarEvent(
            id = "event-1",
            userId = "user-1",
            title = "Email Event",
            status = EventStatus.PENDING_REVIEW,
            eventSources = listOf(emailSource)
        )
        coEvery { eventRepository.getEventWithSources("event-1") } returns
                EventResult.Success(event)

        val viewModel = createViewModel("event-1")
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.uiState.test {
            val state = awaitItem()
            assertEquals(SourceOrigin.EMAIL, state.sourceOrigin)
            assertEquals(testEmail, state.sourceEmail)
            assertEquals("Email Event", state.title)
        }
    }

    @Test
    fun `loads event with google photos source origin`() = runTest {
        val photoSource = EventSource(
            id = "source-2",
            eventId = "event-2",
            emailId = null,
            sourceOrigin = SourceOrigin.GOOGLE_PHOTOS,
            sourceType = SourceType.NEW_INVITATION
        )
        val event = CalendarEvent(
            id = "event-2",
            userId = "user-1",
            title = "Photo Event",
            status = EventStatus.PENDING_REVIEW,
            eventSources = listOf(photoSource)
        )
        coEvery { eventRepository.getEventWithSources("event-2") } returns
                EventResult.Success(event)

        val viewModel = createViewModel("event-2")
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.uiState.test {
            val state = awaitItem()
            assertEquals(SourceOrigin.GOOGLE_PHOTOS, state.sourceOrigin)
            assertNull(state.sourceEmail)
            assertEquals("Photo Event", state.title)
        }
    }

    @Test
    fun `loads event with google calendar source origin`() = runTest {
        val calendarSource = EventSource(
            id = "source-3",
            eventId = "event-3",
            emailId = null,
            sourceOrigin = SourceOrigin.GOOGLE_CALENDAR,
            sourceType = SourceType.NEW_INVITATION
        )
        val event = CalendarEvent(
            id = "event-3",
            userId = "user-1",
            title = "Calendar Event",
            status = EventStatus.PENDING_REVIEW,
            eventSources = listOf(calendarSource)
        )
        coEvery { eventRepository.getEventWithSources("event-3") } returns
                EventResult.Success(event)

        val viewModel = createViewModel("event-3")
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.uiState.test {
            val state = awaitItem()
            assertEquals(SourceOrigin.GOOGLE_CALENDAR, state.sourceOrigin)
            assertNull(state.sourceEmail)
            assertEquals("Calendar Event", state.title)
        }
    }

    @Test
    fun `defaults to email source origin when no sources`() = runTest {
        val event = CalendarEvent(
            id = "event-4",
            userId = "user-1",
            title = "No Source Event",
            status = EventStatus.PENDING_REVIEW,
            eventSources = emptyList()
        )
        coEvery { eventRepository.getEventWithSources("event-4") } returns
                EventResult.Success(event)

        val viewModel = createViewModel("event-4")
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.uiState.test {
            val state = awaitItem()
            assertEquals(SourceOrigin.EMAIL, state.sourceOrigin)
            assertNull(state.sourceEmail)
        }
    }

    @Test
    fun `approveEvent aborts when save fails`() = runTest {
        val event = CalendarEvent(
            id = "event-5",
            userId = "user-1",
            title = "Test Event",
            status = EventStatus.PENDING_REVIEW,
            eventSources = emptyList()
        )
        coEvery { eventRepository.getEventWithSources("event-5") } returns
                EventResult.Success(event)
        coEvery { eventRepository.updateEvent(any(), any(), any(), any(), any(), any(), any()) } returns
                EventResult.Error("Save failed")

        val viewModel = createViewModel("event-5")
        testDispatcher.scheduler.advanceUntilIdle()

        // Make a change to set hasUnsavedChanges = true
        viewModel.onTitleChange("Updated Title")

        // Attempt to approve
        viewModel.approveEvent()
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.uiState.test {
            val state = awaitItem()
            // Approval should NOT have proceeded
            assertFalse(state.isDone)
            assertFalse(state.isApproving)
            assertEquals("Failed to save changes. Please try again.", state.errorMessage)
        }

        // Verify approveEvent was never called on the repository
        coVerify(exactly = 0) { eventRepository.approveEvent(any()) }
    }

    @Test
    fun `expired calendar keeps event editable but blocks approval`() = runTest {
        val event = CalendarEvent(
            id = "event-expired",
            userId = "user-1",
            title = "Review me",
            status = EventStatus.PENDING_REVIEW,
            eventSources = emptyList()
        )
        coEvery { eventRepository.getEventWithSources("event-expired") } returns
            EventResult.Success(event)
        coEvery { integrationRepository.fetchIntegrations() } returns IntegrationResult.Success(
            listOf(
                Integration(
                    id = "calendar",
                    userId = "user-1",
                    provider = IntegrationProvider.GOOGLE_CALENDAR,
                    status = IntegrationStatus.EXPIRED
                )
            )
        )

        val viewModel = createViewModel("event-expired")
        testDispatcher.scheduler.advanceUntilIdle()
        viewModel.onTitleChange("Still editable")
        viewModel.approveEvent()
        testDispatcher.scheduler.advanceUntilIdle()

        assertEquals("Still editable", viewModel.uiState.value.title)
        assertEquals(
            "Reconnect Google Calendar to accept suggestions.",
            viewModel.uiState.value.errorMessage
        )
        coVerify(exactly = 0) { eventRepository.approveEvent(any()) }
    }

    // --- C9.3: reject on an unloaded event does not fabricate one (#278 parity) ---

    @Test
    fun `reject on unloaded event does not fabricate one`() = runTest {
        coEvery { eventRepository.rejectEvent("event-ghost") } returns
                EventResult.Success(
                    CalendarEvent(id = "event-ghost", userId = "user-1", title = "Ghost")
                )

        val viewModel = createViewModel("event-ghost")
        // Intentionally do NOT load the event.
        viewModel.rejectEvent()
        testDispatcher.scheduler.runCurrent()

        val state = viewModel.uiState.value
        assertEquals(true, state.showUndoSnackbar)
        assertEquals("Event rejected", state.undoSnackbarMessage)
        assertNull("unloaded reject must not fabricate a stored event", state.lastRejectedEvent)
    }
}
