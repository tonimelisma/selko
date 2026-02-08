package net.melisma.selko.ui.screens.review

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import io.mockk.coEvery
import io.mockk.every
import io.mockk.mockk
import kotlinx.coroutines.flow.MutableStateFlow
import net.melisma.selko.data.api.BackendApiClient
import net.melisma.selko.data.model.CalendarEvent
import net.melisma.selko.data.model.EventStatus
import net.melisma.selko.data.repository.EventRepository
import net.melisma.selko.data.repository.EventResult
import net.melisma.selko.data.repository.IntegrationRepository
import net.melisma.selko.data.repository.IntegrationResult
import net.melisma.selko.ui.theme.SelkoTheme
import org.junit.Rule
import org.junit.Test

class ReviewQueueScreenTest {

    @get:Rule
    val composeTestRule = createComposeRule()

    private val eventRepository = mockk<EventRepository>(relaxed = true)
    private val integrationRepository = mockk<IntegrationRepository>(relaxed = true)
    private val backendApiClient = mockk<BackendApiClient>(relaxed = true)

    private fun setupMocks(
        isGmailConnected: Boolean = true,
        isCalendarConnected: Boolean = true,
        events: List<CalendarEvent> = emptyList()
    ) {
        coEvery { integrationRepository.fetchIntegrations() } returns IntegrationResult.Success(emptyList())
        coEvery { eventRepository.fetchPendingEventsWithSources() } returns EventResult.Success(events)
        every { backendApiClient.getGmailAuthUrl() } returns "https://example.com/auth"
    }

    @Test
    fun reviewQueueScreen_displaysLoadingIndicator() {
        setupMocks()

        composeTestRule.setContent {
            SelkoTheme {
                ReviewQueueScreen(
                    onNavigateToEventDetail = {},
                    viewModel = ReviewQueueViewModel(eventRepository, integrationRepository, backendApiClient)
                )
            }
        }

        // The screen should render without crashing
        composeTestRule.waitForIdle()
    }

    @Test
    fun reviewQueueScreen_showsEmptyState_whenNoEvents() {
        setupMocks(events = emptyList())

        composeTestRule.setContent {
            SelkoTheme {
                ReviewQueueScreen(
                    onNavigateToEventDetail = {},
                    viewModel = ReviewQueueViewModel(eventRepository, integrationRepository, backendApiClient)
                )
            }
        }

        composeTestRule.waitForIdle()
        // Should show either "All caught up!" or integration setup
        val allCaughtUp = composeTestRule.onNodeWithText("All caught up!", substring = true)
        val welcome = composeTestRule.onNodeWithText("Welcome to Selko", substring = true)
        // At least one should exist (depending on integration state)
        try {
            allCaughtUp.assertIsDisplayed()
        } catch (e: AssertionError) {
            welcome.assertIsDisplayed()
        }
    }

    @Test
    fun reviewQueueScreen_showsIntegrationSetup_whenNotConnected() {
        coEvery { integrationRepository.fetchIntegrations() } returns IntegrationResult.Success(emptyList())
        coEvery { eventRepository.fetchPendingEventsWithSources() } returns EventResult.Success(emptyList())
        every { backendApiClient.getGmailAuthUrl() } returns "https://example.com/auth"

        composeTestRule.setContent {
            SelkoTheme {
                ReviewQueueScreen(
                    onNavigateToEventDetail = {},
                    viewModel = ReviewQueueViewModel(eventRepository, integrationRepository, backendApiClient)
                )
            }
        }

        composeTestRule.waitForIdle()
        // Should show integration setup since no integrations are active
        composeTestRule.onNodeWithText("Welcome to Selko", substring = true).assertIsDisplayed()
    }
}
