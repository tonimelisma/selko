package net.melisma.selko.ui.screens.history

import android.app.Application
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.assertHasClickAction
import androidx.compose.ui.test.getUnclippedBoundsInRoot
import androidx.compose.ui.unit.dp
import androidx.test.core.app.ApplicationProvider
import io.mockk.coEvery
import io.mockk.mockk
import net.melisma.selko.data.api.BackendApiClient
import net.melisma.selko.data.repository.EventRepository
import net.melisma.selko.data.repository.EventResult
import net.melisma.selko.data.repository.IntegrationRepository
import net.melisma.selko.data.model.CalendarEvent
import net.melisma.selko.data.model.CalendarWorkAction
import net.melisma.selko.data.model.CalendarWorkItem
import net.melisma.selko.data.model.CalendarWorkStatus
import net.melisma.selko.data.model.EventReviewStatus
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
        composeTestRule.onNodeWithText("Events you approve or reject will appear here.").assertIsDisplayed()
    }

    @Test
    fun historyScreen_usesPlainStatusTagAnd48DpTertiaryUndo() {
        coEvery { eventRepository.fetchActivityEvents(any(), any()) } returns EventResult.Success(listOf(
            CalendarEvent(
                id = "event-1", userId = "user-1", title = "Project review",
                reviewStatus = EventReviewStatus.ACTIVE,
                googleCalendarEventId = "google-event-1",
                updatedAt = kotlin.time.Instant.parse("2026-07-18T12:00:00Z")
            )
        ))
        composeTestRule.setContent {
            SelkoTheme {
                HistoryScreen(HistoryViewModel(application, eventRepository, integrationRepository, backendApiClient))
            }
        }
        composeTestRule.waitForIdle()

        composeTestRule.onNodeWithText("Synced to Google Calendar").assertIsDisplayed()
        composeTestRule.onNodeWithText("NEW").assertIsDisplayed()
        val undo = composeTestRule.onNodeWithText("Undo").assertHasClickAction()
        val bounds = undo.getUnclippedBoundsInRoot()
        assert(bounds.bottom - bounds.top >= 48.dp)
    }

    @Test
    fun historyScreen_showsCancellationQueuedWithoutUndo() {
        coEvery { eventRepository.fetchActivityEvents(any(), any()) } returns EventResult.Success(listOf(
            CalendarEvent(
                id = "event-cancel", userId = "user-1", title = "Cancelled meeting",
                reviewStatus = EventReviewStatus.ACTIVE,
                calendarWorkItems = listOf(
                    CalendarWorkItem(
                        id = "work-cancel", eventId = "event-cancel", userId = "user-1",
                        action = CalendarWorkAction.CANCEL, generation = 1, status = CalendarWorkStatus.PENDING
                    )
                ),
                updatedAt = kotlin.time.Instant.parse("2026-07-18T12:00:00Z")
            )
        ))
        composeTestRule.setContent {
            SelkoTheme {
                HistoryScreen(HistoryViewModel(application, eventRepository, integrationRepository, backendApiClient))
            }
        }
        composeTestRule.waitForIdle()

        composeTestRule.onNodeWithText("Cancellation queued").assertIsDisplayed()
        composeTestRule.onNodeWithText("Undo").assertDoesNotExist()
    }
}
