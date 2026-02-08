package net.melisma.selko.ui.screens.history

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import io.mockk.coEvery
import io.mockk.mockk
import net.melisma.selko.data.repository.EventRepository
import net.melisma.selko.data.repository.EventResult
import net.melisma.selko.data.repository.IntegrationRepository
import net.melisma.selko.ui.theme.SelkoTheme
import org.junit.Rule
import org.junit.Test

class HistoryScreenTest {

    @get:Rule
    val composeTestRule = createComposeRule()

    private val eventRepository = mockk<EventRepository>(relaxed = true)
    private val integrationRepository = mockk<IntegrationRepository>(relaxed = true)

    @Test
    fun historyScreen_showsEmptyState_whenNoEvents() {
        coEvery { eventRepository.fetchActivityEvents(any(), any()) } returns EventResult.Success(emptyList())

        composeTestRule.setContent {
            SelkoTheme {
                HistoryScreen(
                    viewModel = HistoryViewModel(eventRepository, integrationRepository)
                )
            }
        }

        composeTestRule.waitForIdle()
        composeTestRule.onNodeWithText("No Activity Yet").assertIsDisplayed()
    }

    @Test
    fun historyScreen_showsEmptyStateDescription() {
        coEvery { eventRepository.fetchActivityEvents(any(), any()) } returns EventResult.Success(emptyList())

        composeTestRule.setContent {
            SelkoTheme {
                HistoryScreen(
                    viewModel = HistoryViewModel(eventRepository, integrationRepository)
                )
            }
        }

        composeTestRule.waitForIdle()
        composeTestRule.onNodeWithText("Events you approve or reject will appear here", substring = true).assertIsDisplayed()
    }
}
