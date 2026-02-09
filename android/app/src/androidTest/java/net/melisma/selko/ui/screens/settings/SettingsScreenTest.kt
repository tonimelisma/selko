package net.melisma.selko.ui.screens.settings

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import io.mockk.coEvery
import io.mockk.every
import io.mockk.mockk
import kotlinx.coroutines.flow.MutableStateFlow
import net.melisma.selko.data.api.BackendApiClient
import net.melisma.selko.data.repository.AuthRepository
import net.melisma.selko.data.repository.CalendarSettingsRepository
import net.melisma.selko.data.repository.IntegrationRepository
import net.melisma.selko.data.repository.IntegrationResult
import net.melisma.selko.ui.theme.SelkoTheme
import org.junit.Rule
import org.junit.Test

class SettingsScreenTest {

    @get:Rule
    val composeTestRule = createComposeRule()

    private val authRepository = mockk<AuthRepository>(relaxed = true)
    private val integrationRepository = mockk<IntegrationRepository>(relaxed = true)
    private val calendarSettingsRepository = mockk<CalendarSettingsRepository>(relaxed = true)
    private val backendApiClient = mockk<BackendApiClient>(relaxed = true)

    private fun setupMocks() {
        coEvery { authRepository.getCurrentUserEmail() } returns "test@example.com"
        coEvery { integrationRepository.fetchIntegrations() } returns IntegrationResult.Success(emptyList())
        every { backendApiClient.getGmailAuthUrl() } returns "https://example.com/auth"
        every { backendApiClient.getCalendarAuthUrl() } returns "https://example.com/calendar-auth"
    }

    @Test
    fun settingsScreen_displaysTitle() {
        setupMocks()

        composeTestRule.setContent {
            SelkoTheme {
                SettingsScreen(
                    onLogout = {},
                    viewModel = SettingsViewModel(authRepository, integrationRepository, calendarSettingsRepository, backendApiClient)
                )
            }
        }

        composeTestRule.waitForIdle()
        composeTestRule.onNodeWithText("Settings").assertIsDisplayed()
    }

    @Test
    fun settingsScreen_showsConnectedAccountsSection() {
        setupMocks()

        composeTestRule.setContent {
            SelkoTheme {
                SettingsScreen(
                    onLogout = {},
                    viewModel = SettingsViewModel(authRepository, integrationRepository, calendarSettingsRepository, backendApiClient)
                )
            }
        }

        composeTestRule.waitForIdle()
        composeTestRule.onNodeWithText("Connected Accounts").assertIsDisplayed()
    }

    @Test
    fun settingsScreen_showsCalendarDefaultsSection() {
        setupMocks()

        composeTestRule.setContent {
            SelkoTheme {
                SettingsScreen(
                    onLogout = {},
                    viewModel = SettingsViewModel(authRepository, integrationRepository, calendarSettingsRepository, backendApiClient)
                )
            }
        }

        composeTestRule.waitForIdle()
        composeTestRule.onNodeWithText("Calendar Defaults").assertIsDisplayed()
    }

    @Test
    fun settingsScreen_showsAccountSection() {
        setupMocks()

        composeTestRule.setContent {
            SelkoTheme {
                SettingsScreen(
                    onLogout = {},
                    viewModel = SettingsViewModel(authRepository, integrationRepository, calendarSettingsRepository, backendApiClient)
                )
            }
        }

        composeTestRule.waitForIdle()
        composeTestRule.onNodeWithText("Account").assertIsDisplayed()
    }

    @Test
    fun settingsScreen_showsLogOutButton() {
        setupMocks()

        composeTestRule.setContent {
            SelkoTheme {
                SettingsScreen(
                    onLogout = {},
                    viewModel = SettingsViewModel(authRepository, integrationRepository, calendarSettingsRepository, backendApiClient)
                )
            }
        }

        composeTestRule.waitForIdle()
        composeTestRule.onNodeWithText("Log out").assertIsDisplayed()
    }

    @Test
    fun settingsScreen_showsUserEmail() {
        setupMocks()

        composeTestRule.setContent {
            SelkoTheme {
                SettingsScreen(
                    onLogout = {},
                    viewModel = SettingsViewModel(authRepository, integrationRepository, calendarSettingsRepository, backendApiClient)
                )
            }
        }

        composeTestRule.waitForIdle()
        composeTestRule.onNodeWithText("test@example.com").assertIsDisplayed()
    }

    @Test
    fun settingsScreen_showsGmailIntegration() {
        setupMocks()

        composeTestRule.setContent {
            SelkoTheme {
                SettingsScreen(
                    onLogout = {},
                    viewModel = SettingsViewModel(authRepository, integrationRepository, calendarSettingsRepository, backendApiClient)
                )
            }
        }

        composeTestRule.waitForIdle()
        composeTestRule.onNodeWithText("Gmail").assertIsDisplayed()
    }

    @Test
    fun settingsScreen_showsGoogleCalendarIntegration() {
        setupMocks()

        composeTestRule.setContent {
            SelkoTheme {
                SettingsScreen(
                    onLogout = {},
                    viewModel = SettingsViewModel(authRepository, integrationRepository, calendarSettingsRepository, backendApiClient)
                )
            }
        }

        composeTestRule.waitForIdle()
        composeTestRule.onNodeWithText("Google Calendar").assertIsDisplayed()
    }
}
