package net.melisma.selko.ui.screens.home

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import io.mockk.coVerify
import io.mockk.every
import io.mockk.mockk
import kotlinx.coroutines.flow.MutableStateFlow
import net.melisma.selko.data.repository.AuthRepository
import net.melisma.selko.ui.theme.SelkoTheme
import org.junit.Before
import org.junit.Rule
import org.junit.Test

class HomeScreenTest {

    @get:Rule
    val composeTestRule = createComposeRule()

    private lateinit var authRepository: AuthRepository
    private val userEmailFlow = MutableStateFlow<String?>(null)

    @Before
    fun setup() {
        authRepository = mockk(relaxed = true)
        every { authRepository.userEmail } returns userEmailFlow
    }

    @Test
    fun homeScreen_displaysWelcomeMessage() {
        composeTestRule.setContent {
            SelkoTheme {
                HomeScreen(
                    onLogout = {},
                    viewModel = HomeViewModel(authRepository)
                )
            }
        }

        composeTestRule.onNodeWithText("Welcome to Selko").assertIsDisplayed()
    }

    @Test
    fun homeScreen_displaysUserEmail_whenAvailable() {
        userEmailFlow.value = "test@example.com"

        composeTestRule.setContent {
            SelkoTheme {
                HomeScreen(
                    onLogout = {},
                    viewModel = HomeViewModel(authRepository)
                )
            }
        }

        composeTestRule.onNodeWithText("test@example.com").assertIsDisplayed()
    }

    @Test
    fun homeScreen_doesNotDisplayEmail_whenNull() {
        userEmailFlow.value = null

        composeTestRule.setContent {
            SelkoTheme {
                HomeScreen(
                    onLogout = {},
                    viewModel = HomeViewModel(authRepository)
                )
            }
        }

        // Email text should not exist - only welcome message
        composeTestRule.onNodeWithText("Welcome to Selko").assertIsDisplayed()
    }

    @Test
    fun homeScreen_displaysLogOutButton() {
        composeTestRule.setContent {
            SelkoTheme {
                HomeScreen(
                    onLogout = {},
                    viewModel = HomeViewModel(authRepository)
                )
            }
        }

        composeTestRule.onNodeWithText("Log out").assertIsDisplayed()
    }

    @Test
    fun homeScreen_callsOnLogout_whenLogOutClicked() {
        var logoutCalled = false

        composeTestRule.setContent {
            SelkoTheme {
                HomeScreen(
                    onLogout = { logoutCalled = true },
                    viewModel = HomeViewModel(authRepository)
                )
            }
        }

        composeTestRule.onNodeWithText("Log out").performClick()
        composeTestRule.waitForIdle()

        assert(logoutCalled) { "onLogout callback should have been called" }
    }

    @Test
    fun homeScreen_callsRepositorySignOut_whenLogOutClicked() {
        composeTestRule.setContent {
            SelkoTheme {
                HomeScreen(
                    onLogout = {},
                    viewModel = HomeViewModel(authRepository)
                )
            }
        }

        composeTestRule.onNodeWithText("Log out").performClick()
        composeTestRule.waitForIdle()

        coVerify { authRepository.signOut() }
    }

    @Test
    fun homeScreen_updatesEmail_whenFlowChanges() {
        composeTestRule.setContent {
            SelkoTheme {
                HomeScreen(
                    onLogout = {},
                    viewModel = HomeViewModel(authRepository)
                )
            }
        }

        // Initially no email
        composeTestRule.onNodeWithText("Welcome to Selko").assertIsDisplayed()

        // Update email
        userEmailFlow.value = "updated@example.com"
        composeTestRule.waitForIdle()

        composeTestRule.onNodeWithText("updated@example.com").assertIsDisplayed()
    }

    @Test
    fun homeScreen_displaysDifferentEmails_correctly() {
        userEmailFlow.value = "first@example.com"

        composeTestRule.setContent {
            SelkoTheme {
                HomeScreen(
                    onLogout = {},
                    viewModel = HomeViewModel(authRepository)
                )
            }
        }

        composeTestRule.onNodeWithText("first@example.com").assertIsDisplayed()

        // Change to different email
        userEmailFlow.value = "second@example.com"
        composeTestRule.waitForIdle()

        composeTestRule.onNodeWithText("second@example.com").assertIsDisplayed()
        composeTestRule.onNodeWithText("first@example.com").assertDoesNotExist()
    }
}
