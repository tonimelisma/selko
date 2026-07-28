package net.melisma.selko.ui.screens.review

import android.app.Application
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.test.core.app.ApplicationProvider
import io.mockk.coEvery
import io.mockk.mockk
import net.melisma.selko.data.api.BackendApiClient
import net.melisma.selko.data.repository.EventRepository
import net.melisma.selko.data.repository.EventResult
import net.melisma.selko.data.repository.IntegrationRepository
import net.melisma.selko.ui.theme.SelkoTheme
import org.junit.Rule
import org.junit.Test

class EventDetailScreenTest {

    @get:Rule
    val composeTestRule = createComposeRule()

    private val application = ApplicationProvider.getApplicationContext<Application>()
    private val eventRepository = mockk<EventRepository>(relaxed = true)
    private val integrationRepository = mockk<IntegrationRepository>(relaxed = true)
    private val backendApiClient = mockk<BackendApiClient>(relaxed = true)

    private fun viewModel(eventId: String) = EventDetailViewModel(
        application,
        eventRepository,
        integrationRepository,
        backendApiClient,
        eventId
    )

    @Test
    fun eventDetailScreen_displaysTopBar() {
        coEvery { eventRepository.getEventWithSources(any()) } returns EventResult.Error("Not found")

        composeTestRule.setContent {
            SelkoTheme {
                EventDetailScreen(
                    eventId = "test-event-id",
                    onNavigateBack = {},
                    viewModel = viewModel("test-event-id")
                )
            }
        }

        composeTestRule.waitForIdle()
        composeTestRule.onNodeWithText("Event Details").assertIsDisplayed()
    }

    @Test
    fun eventDetailScreen_showsBackButton() {
        coEvery { eventRepository.getEventWithSources(any()) } returns EventResult.Error("Not found")

        composeTestRule.setContent {
            SelkoTheme {
                EventDetailScreen(
                    eventId = "test-event-id",
                    onNavigateBack = {},
                    viewModel = viewModel("test-event-id")
                )
            }
        }

        composeTestRule.waitForIdle()
        composeTestRule.onNodeWithContentDescription("Back").assertIsDisplayed()
    }

    @Test
    fun eventDetailScreen_showsErrorForMissingEvent() {
        coEvery { eventRepository.getEventWithSources(any()) } returns EventResult.Error("Event not found")

        composeTestRule.setContent {
            SelkoTheme {
                EventDetailScreen(
                    eventId = "nonexistent-id",
                    onNavigateBack = {},
                    viewModel = viewModel("nonexistent-id")
                )
            }
        }

        composeTestRule.waitForIdle()
        composeTestRule.onNodeWithText("Event not found", substring = true).assertIsDisplayed()
    }
}
