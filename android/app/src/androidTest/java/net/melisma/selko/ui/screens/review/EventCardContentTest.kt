package net.melisma.selko.ui.screens.review

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.ext.junit.runners.AndroidJUnit4
import kotlin.test.assertTrue
import kotlin.time.Instant
import net.melisma.selko.data.model.CalendarEvent
import net.melisma.selko.ui.theme.SelkoTheme
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class EventCardContentTest {

    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun eventCard_hasVisibleLabeledPeerActionsWithEventContext() {
        val clicked = mutableListOf<String>()
        val event = CalendarEvent(
            id = "event-1",
            userId = "user-1",
            title = "Team Meeting",
            startDatetime = Instant.parse("2026-07-31T10:00:00Z")
        )

        composeTestRule.setContent {
            SelkoTheme {
                EventListItem(
                    event = event,
                    isProcessing = false,
                    onApprove = { clicked += "accept" },
                    onReject = { clicked += "reject" },
                    onEdit = { clicked += "edit" }
                )
            }
        }

        composeTestRule.onNodeWithText("Accept").assertIsDisplayed()
        composeTestRule.onNodeWithText("Edit").assertIsDisplayed()
        composeTestRule.onNodeWithText("Reject").assertIsDisplayed()
        composeTestRule.onNodeWithContentDescription("Accept Team Meeting").assertIsDisplayed()
        composeTestRule.onNodeWithContentDescription("Edit Team Meeting").assertIsDisplayed()
        composeTestRule.onNodeWithContentDescription("Reject Team Meeting").assertIsDisplayed()

        composeTestRule.onNodeWithText("Edit").performClick()
        assertTrue(clicked == listOf("edit"))
    }
}
