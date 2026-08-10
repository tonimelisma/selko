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
import net.melisma.selko.data.model.SourceType
import net.melisma.selko.data.model.Integration
import net.melisma.selko.data.model.IntegrationProvider
import net.melisma.selko.data.model.IntegrationStatus
import net.melisma.selko.data.model.SenderRule
import net.melisma.selko.data.repository.EventRepository
import net.melisma.selko.data.repository.EventResult
import net.melisma.selko.data.repository.IntegrationRepository
import net.melisma.selko.data.repository.IntegrationResult
import net.melisma.selko.data.repository.RepositoryResult
import net.melisma.selko.data.repository.SenderRuleRepository
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import io.mockk.coVerify
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class ReviewQueueViewModelTest {

    private lateinit var application: Application
    private lateinit var eventRepository: EventRepository
    private lateinit var integrationRepository: IntegrationRepository
    private lateinit var backendApiClient: BackendApiClient
    private lateinit var senderRuleRepository: SenderRuleRepository
    private lateinit var viewModel: ReviewQueueViewModel
    private val testDispatcher = StandardTestDispatcher()

    private val testIntegrations = listOf(
        Integration(
            id = "int-1",
            userId = "user-1",
            provider = IntegrationProvider.GMAIL,
            status = IntegrationStatus.ACTIVE
        ),
        Integration(
            id = "int-2",
            userId = "user-1",
            provider = IntegrationProvider.GOOGLE_CALENDAR,
            status = IntegrationStatus.ACTIVE
        )
    )

    @Test
    fun `parked Google Photos does not create a recovery action`() {
        val integrations = testIntegrations + Integration(
            id = "int-photo",
            userId = "user-1",
            provider = IntegrationProvider.GOOGLE_PHOTOS,
            status = IntegrationStatus.EXPIRED
        )

        assertEquals(emptyList<IntegrationProvider>(), recoveryProvidersFor(integrations))
    }

    private val testEmail = Email(
        id = "email-1",
        userId = "user-1",
        subject = "Test Event",
        fromEmail = "sender@example.com",
        fromName = "Test Sender"
    )

    private val testEventSource = EventSource(
        id = "source-1",
        eventId = "event-1",
        emailId = "email-1",
        sourceType = SourceType.NEW_INVITATION,
        emails = testEmail
    )

    private val testEvents = listOf(
        CalendarEvent(
            id = "event-1",
            userId = "user-1",
            title = "Test Event 1",
            status = EventStatus.PENDING_REVIEW,
            eventSources = listOf(testEventSource)
        ),
        CalendarEvent(
            id = "event-2",
            userId = "user-1",
            title = "Test Event 2",
            status = EventStatus.PENDING_REVIEW,
            eventSources = listOf(
                testEventSource.copy(id = "source-2", eventId = "event-2")
            )
        )
    )

    @Before
    fun setup() {
        Dispatchers.setMain(testDispatcher)
        application = mockk(relaxed = true)
        every { application.getString(R.string.review_error_approve) } returns "Failed to approve event"
        every { application.getString(R.string.review_error_reject) } returns "Failed to reject event"
        every { application.getString(R.string.review_error_ignore_rule) } returns "Failed to create ignore rule"
        every { application.getString(R.string.review_error_auto_approve_rule) } returns "Failed to create auto-approve rule"
        every {
            application.getString(R.string.review_calendar_reconnect_required)
        } returns "Reconnect Google Calendar to accept suggestions."
        eventRepository = mockk(relaxed = true)
        integrationRepository = mockk(relaxed = true)
        backendApiClient = mockk(relaxed = true)
        senderRuleRepository = mockk(relaxed = true)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun createViewModel(
        integrations: List<Integration> = testIntegrations
    ): ReviewQueueViewModel {
        coEvery { integrationRepository.fetchIntegrations() } returns
                IntegrationResult.Success(integrations)
        coEvery { eventRepository.fetchPendingEventsWithSources() } returns
                EventResult.Success(testEvents)

        return ReviewQueueViewModel(
            application,
            eventRepository,
            integrationRepository,
            backendApiClient,
            senderRuleRepository
        )
    }

    @Test
    fun `OAuth start delegates to the authenticated backend client`() = runTest {
        coEvery {
            backendApiClient.startOAuth(IntegrationProvider.GMAIL)
        } returns Result.success("https://accounts.example/authorize")
        viewModel = createViewModel()

        val result = viewModel.startOAuth(IntegrationProvider.GMAIL)

        assertEquals("https://accounts.example/authorize", result.getOrThrow())
        coVerify(exactly = 1) {
            backendApiClient.startOAuth(IntegrationProvider.GMAIL)
        }
    }

    @Test
    fun `active Outlook satisfies the email requirement and loads suggestions`() = runTest {
        val integrations = listOf(
            testIntegrations[0].copy(status = IntegrationStatus.EXPIRED),
            testIntegrations[0].copy(
                id = "int-outlook",
                provider = IntegrationProvider.OUTLOOK,
                status = IntegrationStatus.ACTIVE
            ),
            testIntegrations[1]
        )

        viewModel = createViewModel(integrations)
        testDispatcher.scheduler.advanceUntilIdle()

        assertTrue(viewModel.uiState.value.isEmailConnected)
        assertEquals(2, viewModel.uiState.value.events.size)
    }

    @Test
    fun `expired calendar keeps suggestions visible and blocks approval`() = runTest {
        val integrations = listOf(
            testIntegrations[0].copy(provider = IntegrationProvider.OUTLOOK),
            testIntegrations[1].copy(status = IntegrationStatus.EXPIRED)
        )
        viewModel = createViewModel(integrations)
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.approveEvent("event-1")
        testDispatcher.scheduler.advanceUntilIdle()

        assertEquals(2, viewModel.uiState.value.events.size)
        assertEquals(
            "Reconnect Google Calendar to accept suggestions.",
            viewModel.uiState.value.errorMessage
        )
        coVerify(exactly = 0) { eventRepository.approveEvent(any()) }
    }

    @Test
    fun `ignoreSender creates rule and rejects events`() = runTest {
        val testRule = SenderRule(
            id = "rule-1",
            userId = "user-1",
            senderEmail = "sender@example.com",
            action = "ignore",
            createdAt = "2026-01-01T00:00:00Z"
        )
        coEvery {
            senderRuleRepository.createRule("sender@example.com", null, "ignore")
        } returns RepositoryResult.Success(testRule)
        coEvery { eventRepository.rejectEvent(any()) } returns
                EventResult.Success(testEvents[0].copy(status = EventStatus.REJECTED))

        viewModel = createViewModel()
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.ignoreSender("sender@example.com")
        testDispatcher.scheduler.advanceUntilIdle()

        coVerify { senderRuleRepository.createRule("sender@example.com", null, "ignore") }
        coVerify(atLeast = 1) { eventRepository.rejectEvent(any()) }
    }

    @Test
    fun `autoApproveSender creates rule and approves events`() = runTest {
        val testRule = SenderRule(
            id = "rule-1",
            userId = "user-1",
            senderEmail = "sender@example.com",
            action = "auto_approve",
            createdAt = "2026-01-01T00:00:00Z"
        )
        coEvery {
            senderRuleRepository.createRule("sender@example.com", null, "auto_approve")
        } returns RepositoryResult.Success(testRule)
        coEvery { eventRepository.approveEvent(any()) } returns
                EventResult.Success(testEvents[0].copy(status = EventStatus.APPROVED))

        viewModel = createViewModel()
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.autoApproveSender("sender@example.com")
        testDispatcher.scheduler.advanceUntilIdle()

        coVerify { senderRuleRepository.createRule("sender@example.com", null, "auto_approve") }
        coVerify(atLeast = 1) { eventRepository.approveEvent(any()) }
        coVerify(exactly = 0) { backendApiClient.syncEventToCalendar(any()) }
    }

    @Test
    fun `ignoreSender shows error on failure`() = runTest {
        coEvery {
            senderRuleRepository.createRule(any(), any(), any())
        } returns RepositoryResult.Error("Network error")

        viewModel = createViewModel()
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.ignoreSender("sender@example.com")
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.uiState.test {
            val state = awaitItem()
            assertEquals("Failed to create ignore rule", state.errorMessage)
        }
    }

    @Test
    fun `autoApproveSender shows error on failure`() = runTest {
        coEvery {
            senderRuleRepository.createRule(any(), any(), any())
        } returns RepositoryResult.Error("Network error")

        viewModel = createViewModel()
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.autoApproveSender("sender@example.com")
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.uiState.test {
            val state = awaitItem()
            assertEquals("Failed to create auto-approve rule", state.errorMessage)
        }
    }

    @Test
    fun `ignoreSender removes events from state`() = runTest {
        val testRule = SenderRule(
            id = "rule-1",
            userId = "user-1",
            senderEmail = "sender@example.com",
            action = "ignore",
            createdAt = "2026-01-01T00:00:00Z"
        )
        coEvery {
            senderRuleRepository.createRule("sender@example.com", null, "ignore")
        } returns RepositoryResult.Success(testRule)
        coEvery { eventRepository.rejectEvent(any()) } returns
                EventResult.Success(testEvents[0].copy(status = EventStatus.REJECTED))

        viewModel = createViewModel()
        testDispatcher.scheduler.advanceUntilIdle()

        // Verify events are loaded initially
        assertTrue(viewModel.uiState.value.events.isNotEmpty())

        viewModel.ignoreSender("sender@example.com")
        testDispatcher.scheduler.advanceUntilIdle()

        // After ignoring, events from that sender should be removed
        assertTrue(viewModel.uiState.value.events.isEmpty())
    }
}


// --- C9.1: reject-undo parity (mirrors ios/SelkoTests/Review/ReviewQueueViewModelTests.swift) ---

class RejectUndoParityTest {
    @OptIn(ExperimentalCoroutinesApi::class)
    private class Harness {
        val application: Application = mockk(relaxed = true)
        val eventRepository: EventRepository = mockk(relaxed = true)
        val integrationRepository: IntegrationRepository = mockk(relaxed = true)
        val backendApiClient: BackendApiClient = mockk(relaxed = true)
        val senderRuleRepository: SenderRuleRepository = mockk(relaxed = true)
        val dispatcher = StandardTestDispatcher()

        init {
            Dispatchers.setMain(dispatcher)
            every { application.getString(R.string.review_event_rejected) } returns "Event rejected"
            every { application.getString(R.string.review_events_rejected, any()) } returns "2 events rejected"
            every { application.getString(R.string.review_error_reject) } returns "Failed to reject event"
        }

        fun event(id: String, title: String = "Event $id") = CalendarEvent(
            id = id, userId = "user-1", title = title, status = EventStatus.PENDING_REVIEW
        )

        fun viewModel(
            events: List<CalendarEvent> = listOf(event("event-1"), event("event-2")),
            rejectStub: (String) -> EventResult<CalendarEvent> = { EventResult.Success(event(it)) }
        ): ReviewQueueViewModel {
            coEvery { integrationRepository.fetchIntegrations() } returns IntegrationResult.Success(
                listOf(
                    Integration(id = "int-1", userId = "user-1", provider = IntegrationProvider.GMAIL, status = IntegrationStatus.ACTIVE),
                    Integration(id = "int-2", userId = "user-1", provider = IntegrationProvider.GOOGLE_CALENDAR, status = IntegrationStatus.ACTIVE)
                )
            )
            coEvery { eventRepository.fetchPendingEventsWithSources() } returns EventResult.Success(events)
            coEvery { eventRepository.rejectEvent(any()) } answers { call ->
                rejectStub(call.invocation.args[0] as String)
            }
            val vm = ReviewQueueViewModel(
                application, eventRepository, integrationRepository,
                backendApiClient, senderRuleRepository
            )
            dispatcher.scheduler.advanceUntilIdle()
            return vm
        }

        fun finish() {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun `rejecting one event shows the snackbar with the singular string`() = runTest {
        val h = Harness()
        val vm = h.viewModel()
        val target = h.event("event-1")

        vm.rejectEvent("event-1")
        h.dispatcher.scheduler.runCurrent()

        assertEquals(true, vm.uiState.value.showUndoSnackbar)
        assertEquals("Event rejected", vm.uiState.value.undoSnackbarMessage)
        assertEquals(listOf("event-1"), vm.uiState.value.lastRejectedEvents.map { it.id })
        h.finish()
    }

    @Test
    fun `a second reject within 8s combines both and shows the plural string`() = runTest {
        val h = Harness()
        val vm = h.viewModel()

        vm.showRejectUndo(listOf(h.event("event-1")))
        vm.showRejectUndo(listOf(h.event("event-2")))
        h.dispatcher.scheduler.runCurrent()

        assertEquals(2, vm.uiState.value.lastRejectedEvents.size)
        assertEquals("2 events rejected", vm.uiState.value.undoSnackbarMessage)
        assertEquals(true, vm.uiState.value.showUndoSnackbar)
        h.finish()
    }

    @Test
    fun `undo restores every combined event`() = runTest {
        val h = Harness()
        val vm = h.viewModel()
        coEvery { h.backendApiClient.undoHistoryEvent(any()) } returns Result.success(io.mockk.mockk())

        vm.showRejectUndo(listOf(h.event("event-1")))
        vm.showRejectUndo(listOf(h.event("event-2")))
        h.dispatcher.scheduler.runCurrent()
        assertEquals(2, vm.uiState.value.lastRejectedEvents.size)

        vm.undoLastRejected()
        h.dispatcher.scheduler.runCurrent()
        h.dispatcher.scheduler.advanceUntilIdle()

        assertEquals(false, vm.uiState.value.showUndoSnackbar)
        assertEquals(0, vm.uiState.value.lastRejectedEvents.size)
        // Both combined events are restored into the list (refetch also runs).
        val restored = vm.uiState.value.events.map { it.id }
        assertTrue(restored.containsAll(listOf("event-1", "event-2")))
        h.finish()
    }

    @Test
    fun `dismissUndo after 8s clears snackbar and lastRejectedEvents`() = runTest {
        val h = Harness()
        val vm = h.viewModel()

        vm.showRejectUndo(listOf(h.event("event-1")))
        h.dispatcher.scheduler.runCurrent()
        assertEquals(true, vm.uiState.value.showUndoSnackbar)

        h.dispatcher.scheduler.advanceTimeBy(8000)
        h.dispatcher.scheduler.runCurrent()

        assertEquals(false, vm.uiState.value.showUndoSnackbar)
        assertEquals(0, vm.uiState.value.lastRejectedEvents.size)
        h.finish()
    }

    @Test
    fun `two showRejectUndo calls in flight must not lose an event`() = runTest {
        // #278 regression: the combined list is read and written inside the
        // state update, so a second call racing the first must append, not
        // overwrite.
        val h = Harness()
        val vm = h.viewModel()

        vm.showRejectUndo(listOf(h.event("event-1")))
        vm.showRejectUndo(listOf(h.event("event-2")))
        h.dispatcher.scheduler.runCurrent()

        assertEquals(
            listOf("event-1", "event-2"),
            vm.uiState.value.lastRejectedEvents.map { it.id }
        )
        h.finish()
    }

    @Test
    fun `partial-success reject removes only succeeded ids and still refetches`() = runTest {
        val h = Harness()
        val senderSource = EventSource(
            id = "source-g", eventId = "g", emailId = "email-g",
            sourceType = SourceType.NEW_INVITATION,
            emails = Email(
                id = "email-g", userId = "user-1",
                subject = "Group", fromEmail = "sender@example.com", fromName = "Sender"
            )
        )
        val groupEvent1 = h.event("group-1").copy(eventSources = listOf(senderSource.copy(eventId = "group-1")))
        val groupEvent2 = h.event("group-2").copy(eventSources = listOf(senderSource.copy(eventId = "group-2")))
        val vm = h.viewModel(
            events = listOf(groupEvent1, groupEvent2),
            rejectStub = { id ->
                if (id == "group-2") EventResult.Error("boom")
                else EventResult.Success(h.event(id))
            }
        )
        coEvery { h.eventRepository.fetchPendingEventsWithSources() } returns EventResult.Success(listOf(groupEvent2))

        vm.rejectGroup("sender@example.com")
        h.dispatcher.scheduler.runCurrent()

        // Failed event stays, succeeded one is removed.
        assertTrue(vm.uiState.value.events.none { it.id == "group-1" })
        assertTrue(vm.uiState.value.events.any { it.id == "group-2" })
        // Undo snackbar covers only the succeeded ids.
        assertEquals(listOf("group-1"), vm.uiState.value.lastRejectedEvents.map { it.id })
        // Still refetched to reconcile the failed event's real state.
        coVerify(atLeast = 1) { h.eventRepository.fetchPendingEventsWithSources() }
        h.finish()
    }
}
