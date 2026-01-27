package net.melisma.selko.ui.screens.auth

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import io.mockk.coEvery
import io.mockk.every
import io.mockk.mockk
import kotlinx.coroutines.flow.MutableStateFlow
import net.melisma.selko.data.repository.AuthRepository
import net.melisma.selko.data.repository.AuthResult
import net.melisma.selko.ui.theme.SelkoTheme
import org.junit.Before
import org.junit.Rule
import org.junit.Test

class AuthScreenTest {

    @get:Rule
    val composeTestRule = createComposeRule()

    private lateinit var authRepository: AuthRepository

    @Before
    fun setup() {
        authRepository = mockk(relaxed = true)
        every { authRepository.isLoggedIn } returns MutableStateFlow(false)
        every { authRepository.userEmail } returns MutableStateFlow(null)
    }

    @Test
    fun authScreen_displaysSelkoTitle() {
        composeTestRule.setContent {
            SelkoTheme {
                AuthScreen(
                    onAuthSuccess = {},
                    viewModel = AuthViewModel(authRepository)
                )
            }
        }

        composeTestRule.onNodeWithText("Selko").assertIsDisplayed()
    }

    @Test
    fun authScreen_displaysSignInSubtitle_initially() {
        composeTestRule.setContent {
            SelkoTheme {
                AuthScreen(
                    onAuthSuccess = {},
                    viewModel = AuthViewModel(authRepository)
                )
            }
        }

        composeTestRule.onNodeWithText("Sign In").assertIsDisplayed()
    }

    @Test
    fun authScreen_displaysEmailAndPasswordFields() {
        composeTestRule.setContent {
            SelkoTheme {
                AuthScreen(
                    onAuthSuccess = {},
                    viewModel = AuthViewModel(authRepository)
                )
            }
        }

        composeTestRule.onNodeWithText("Email").assertIsDisplayed()
        composeTestRule.onNodeWithText("Password").assertIsDisplayed()
    }

    @Test
    fun authScreen_displaysSignInButton_initially() {
        composeTestRule.setContent {
            SelkoTheme {
                AuthScreen(
                    onAuthSuccess = {},
                    viewModel = AuthViewModel(authRepository)
                )
            }
        }

        composeTestRule.onNode(hasText("Sign In") and !hasText("Don't")).assertIsDisplayed()
    }

    @Test
    fun authScreen_displaysToggleText_forSignUp() {
        composeTestRule.setContent {
            SelkoTheme {
                AuthScreen(
                    onAuthSuccess = {},
                    viewModel = AuthViewModel(authRepository)
                )
            }
        }

        composeTestRule.onNodeWithText("Don't have an account? Sign Up").assertIsDisplayed()
    }

    @Test
    fun authScreen_togglesToSignUp_whenToggleClicked() {
        composeTestRule.setContent {
            SelkoTheme {
                AuthScreen(
                    onAuthSuccess = {},
                    viewModel = AuthViewModel(authRepository)
                )
            }
        }

        composeTestRule.onNodeWithText("Don't have an account? Sign Up").performClick()

        composeTestRule.onNodeWithText("Create Account").assertIsDisplayed()
        composeTestRule.onNodeWithText("Already have an account? Sign In").assertIsDisplayed()
    }

    @Test
    fun authScreen_togglesBackToSignIn_whenToggleClickedTwice() {
        composeTestRule.setContent {
            SelkoTheme {
                AuthScreen(
                    onAuthSuccess = {},
                    viewModel = AuthViewModel(authRepository)
                )
            }
        }

        // Toggle to sign up
        composeTestRule.onNodeWithText("Don't have an account? Sign Up").performClick()
        // Toggle back to sign in
        composeTestRule.onNodeWithText("Already have an account? Sign In").performClick()

        composeTestRule.onNodeWithText("Sign In").assertIsDisplayed()
    }

    @Test
    fun authScreen_showsError_whenSubmittingEmptyFields() {
        composeTestRule.setContent {
            SelkoTheme {
                AuthScreen(
                    onAuthSuccess = {},
                    viewModel = AuthViewModel(authRepository)
                )
            }
        }

        // Click sign in without entering anything
        composeTestRule.onNode(hasText("Sign In") and !hasText("Don't")).performClick()

        composeTestRule.onNodeWithText("Email and password are required").assertIsDisplayed()
    }

    @Test
    fun authScreen_acceptsEmailInput() {
        composeTestRule.setContent {
            SelkoTheme {
                AuthScreen(
                    onAuthSuccess = {},
                    viewModel = AuthViewModel(authRepository)
                )
            }
        }

        composeTestRule.onNodeWithText("Email").performTextInput("test@example.com")

        composeTestRule.onNodeWithText("test@example.com").assertIsDisplayed()
    }

    @Test
    fun authScreen_acceptsPasswordInput() {
        composeTestRule.setContent {
            SelkoTheme {
                AuthScreen(
                    onAuthSuccess = {},
                    viewModel = AuthViewModel(authRepository)
                )
            }
        }

        composeTestRule.onNodeWithText("Password").performTextInput("password123")

        // Password is obscured, so we can't check the text directly
        // But we can verify no error is shown
        composeTestRule.onNodeWithText("Email and password are required").assertDoesNotExist()
    }

    @Test
    fun authScreen_showsErrorOnAuthFailure() {
        coEvery { authRepository.signIn(any(), any()) } returns AuthResult.Error("Invalid credentials")

        composeTestRule.setContent {
            SelkoTheme {
                AuthScreen(
                    onAuthSuccess = {},
                    viewModel = AuthViewModel(authRepository)
                )
            }
        }

        composeTestRule.onNodeWithText("Email").performTextInput("test@example.com")
        composeTestRule.onNodeWithText("Password").performTextInput("wrongpassword")
        composeTestRule.onNode(hasText("Sign In") and !hasText("Don't")).performClick()

        composeTestRule.waitForIdle()
        composeTestRule.onNodeWithText("Invalid credentials").assertIsDisplayed()
    }

    @Test
    fun authScreen_callsOnAuthSuccess_whenAuthSucceeds() {
        var authSuccessCalled = false
        coEvery { authRepository.signIn(any(), any()) } returns AuthResult.Success("test@example.com")

        composeTestRule.setContent {
            SelkoTheme {
                AuthScreen(
                    onAuthSuccess = { authSuccessCalled = true },
                    viewModel = AuthViewModel(authRepository)
                )
            }
        }

        composeTestRule.onNodeWithText("Email").performTextInput("test@example.com")
        composeTestRule.onNodeWithText("Password").performTextInput("password123")
        composeTestRule.onNode(hasText("Sign In") and !hasText("Don't")).performClick()

        composeTestRule.waitForIdle()
        assert(authSuccessCalled) { "onAuthSuccess callback should have been called" }
    }

    @Test
    fun authScreen_clearsError_whenTypingInEmailField() {
        composeTestRule.setContent {
            SelkoTheme {
                AuthScreen(
                    onAuthSuccess = {},
                    viewModel = AuthViewModel(authRepository)
                )
            }
        }

        // Trigger error
        composeTestRule.onNode(hasText("Sign In") and !hasText("Don't")).performClick()
        composeTestRule.onNodeWithText("Email and password are required").assertIsDisplayed()

        // Type in email field
        composeTestRule.onNodeWithText("Email").performTextInput("test@example.com")

        // Error should be cleared
        composeTestRule.onNodeWithText("Email and password are required").assertDoesNotExist()
    }

    @Test
    fun authScreen_clearsError_whenTypingInPasswordField() {
        composeTestRule.setContent {
            SelkoTheme {
                AuthScreen(
                    onAuthSuccess = {},
                    viewModel = AuthViewModel(authRepository)
                )
            }
        }

        // Trigger error
        composeTestRule.onNode(hasText("Sign In") and !hasText("Don't")).performClick()
        composeTestRule.onNodeWithText("Email and password are required").assertIsDisplayed()

        // Type in password field
        composeTestRule.onNodeWithText("Password").performTextInput("password123")

        // Error should be cleared
        composeTestRule.onNodeWithText("Email and password are required").assertDoesNotExist()
    }

    @Test
    fun authScreen_clearsError_whenTogglingAuthMode() {
        composeTestRule.setContent {
            SelkoTheme {
                AuthScreen(
                    onAuthSuccess = {},
                    viewModel = AuthViewModel(authRepository)
                )
            }
        }

        // Trigger error
        composeTestRule.onNode(hasText("Sign In") and !hasText("Don't")).performClick()
        composeTestRule.onNodeWithText("Email and password are required").assertIsDisplayed()

        // Toggle to sign up
        composeTestRule.onNodeWithText("Don't have an account? Sign Up").performClick()

        // Error should be cleared
        composeTestRule.onNodeWithText("Email and password are required").assertDoesNotExist()
    }
}
