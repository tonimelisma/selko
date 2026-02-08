package net.melisma.selko.ui.screens.review

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import io.mockk.coEvery
import io.mockk.mockk
import net.melisma.selko.data.model.CalendarEvent
import net.melisma.selko.data.model.EventStatus
import net.melisma.selko.data.repository.EventRepository
import net.melisma.selko.data.repository.EventResult
import net.melisma.selko.ui.theme.SelkoTheme
import org.junit.Rule
import org.junit.Test

class EventDetailScreenTest {

    @get:Rule
    val composeTestRule = createComposeRule()

    private val eventRepository = mockk<EventRepository>(relaxed = true)

    @Test
    fun eventDetailScreen_displaysTopBar() {
        coEvery { eventRepository.getEventWithSources(any()) } returns EventResult.Error("Not found")

        composeTestRule.setContent {
            SelkoTheme {
                EventDetailScreen(
                    eventId = "test-event-id",
                    onNavigateBack = {},
                    viewModel = EventDetailViewModel(eventRepository, "test-event-id")
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
                    viewModel = EventDetailViewModel(eventRepository, "test-event-id")
                )
            }
        }

        composeTestRule.waitForIdle()
        composeTestRule.onNodeWithText("Back", substring = true, useUnmergedTree = true).assertIsDisplayed()
    }

    @Test
    fun eventDetailScreen_showsErrorForMissingEvent() {
        coEvery { eventRepository.getEventWithSources(any()) } returns EventResult.Error("Event not found")

        composeTestRule.setContent {
            SelkoTheme {
                EventDetailScreen(
                    eventId = "nonexistent-id",
                    onNavigateBack = {},
                    viewModel = EventDetailViewModel(eventRepository, "nonexistent-id")
                )
            }
        }

        composeTestRule.waitForIdle()
        composeTestRule.onNodeWithText("Event not found", substring = true).assertIsDisplayed()
    }
}
