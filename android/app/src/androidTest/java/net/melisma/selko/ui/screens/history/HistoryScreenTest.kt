package net.melisma.selko.ui.screens.history

import android.app.Application
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
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

class HistoryScreenTest {

    @get:Rule
    val composeTestRule = createComposeRule()

    private val application = ApplicationProvider.getApplicationContext<Application>()
    private val eventRepository = mockk<EventRepository>(relaxed = true)
    private val integrationRepository = mockk<IntegrationRepository>(relaxed = true)
    private val backendApiClient = mockk<BackendApiClient>(relaxed = true)

    @Test
    fun historyScreen_showsEmptyState_whenNoEvents() {
        coEvery { eventRepository.fetchActivityEvents(any(), any()) } returns EventResult.Success(emptyList())

        composeTestRule.setContent {
            SelkoTheme {
                HistoryScreen(
                    viewModel = HistoryViewModel(
                        application,
                        eventRepository,
                        integrationRepository,
                        backendApiClient
                    )
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
                    viewModel = HistoryViewModel(
                        application,
                        eventRepository,
                        integrationRepository,
                        backendApiClient
                    )
                )
            }
        }

        composeTestRule.waitForIdle()
        composeTestRule.onNodeWithText("Your approved and rejected events will appear here").assertIsDisplayed()
    }
}
