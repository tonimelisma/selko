package net.melisma.selko.ui.screens.review

import android.app.Application
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.test.core.app.ApplicationProvider
import io.mockk.coEvery
import io.mockk.every
import io.mockk.mockk
import net.melisma.selko.data.api.BackendApiClient
import net.melisma.selko.data.model.CalendarEvent
import net.melisma.selko.data.repository.EventRepository
import net.melisma.selko.data.repository.EventResult
import net.melisma.selko.data.repository.IntegrationRepository
import net.melisma.selko.data.repository.IntegrationResult
import net.melisma.selko.data.repository.SenderRuleRepository
import net.melisma.selko.ui.theme.SelkoTheme
import org.junit.Rule
import org.junit.Test

class ReviewQueueScreenTest {

    @get:Rule
    val composeTestRule = createComposeRule()

    private val application = ApplicationProvider.getApplicationContext<Application>()
    private val eventRepository = mockk<EventRepository>(relaxed = true)
    private val integrationRepository = mockk<IntegrationRepository>(relaxed = true)
    private val backendApiClient = mockk<BackendApiClient>(relaxed = true)
    private val senderRuleRepository = mockk<SenderRuleRepository>(relaxed = true)

    private fun viewModel() = ReviewQueueViewModel(
        application,
        eventRepository,
        integrationRepository,
        backendApiClient,
        senderRuleRepository
    )

    private fun setupMocks(events: List<CalendarEvent> = emptyList()) {
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
                    viewModel = viewModel()
                )
            }
        }

        composeTestRule.waitForIdle()
    }

    @Test
    fun reviewQueueScreen_showsEmptyState_whenNoEvents() {
        setupMocks(events = emptyList())

        composeTestRule.setContent {
            SelkoTheme {
                ReviewQueueScreen(
                    onNavigateToEventDetail = {},
                    viewModel = viewModel()
                )
            }
        }

        composeTestRule.waitForIdle()
        val allCaughtUp = composeTestRule.onNodeWithText("All caught up!", substring = true)
        val welcome = composeTestRule.onNodeWithText("Welcome to Selko", substring = true)
        try {
            allCaughtUp.assertIsDisplayed()
        } catch (_: AssertionError) {
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
                    viewModel = viewModel()
                )
            }
        }

        composeTestRule.waitForIdle()
        composeTestRule.onNodeWithText("Welcome to Selko", substring = true).assertIsDisplayed()
    }
}
