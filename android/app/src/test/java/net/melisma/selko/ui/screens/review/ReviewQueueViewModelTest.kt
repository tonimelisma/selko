package net.melisma.selko.ui.screens.review

import app.cash.turbine.test
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
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
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class ReviewQueueViewModelTest {

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
        eventRepository = mockk(relaxed = true)
        integrationRepository = mockk(relaxed = true)
        backendApiClient = mockk(relaxed = true)
        senderRuleRepository = mockk(relaxed = true)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun createViewModel(): ReviewQueueViewModel {
        coEvery { integrationRepository.fetchIntegrations() } returns
                IntegrationResult.Success(testIntegrations)
        coEvery { eventRepository.fetchPendingEventsWithSources() } returns
                EventResult.Success(testEvents)

        return ReviewQueueViewModel(
            eventRepository,
            integrationRepository,
            backendApiClient,
            senderRuleRepository
        )
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
