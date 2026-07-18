package net.melisma.selko.ui.screens.settings

import android.app.Application
import androidx.test.core.app.ApplicationProvider
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.isToggleable
import androidx.compose.ui.test.performScrollTo
import io.mockk.coEvery
import io.mockk.every
import io.mockk.mockk
import kotlinx.coroutines.flow.MutableStateFlow
import net.melisma.selko.data.api.BackendApiClient
import net.melisma.selko.data.repository.AuthRepository
import net.melisma.selko.data.repository.CalendarSettingsRepository
import net.melisma.selko.data.repository.IntegrationRepository
import net.melisma.selko.data.repository.IntegrationResult
import net.melisma.selko.data.repository.EmailFolderRepository
import net.melisma.selko.data.repository.RepositoryResult
import net.melisma.selko.data.model.EmailFolderPreference
import net.melisma.selko.data.model.Integration
import net.melisma.selko.data.model.IntegrationProvider
import net.melisma.selko.data.model.IntegrationStatus
import net.melisma.selko.data.repository.SenderRuleRepository
import net.melisma.selko.ui.theme.SelkoTheme
import org.junit.Rule
import org.junit.Test

class SettingsScreenTest {

    @get:Rule
    val composeTestRule = createComposeRule()

    private val application = ApplicationProvider.getApplicationContext<Application>()
    private val authRepository = mockk<AuthRepository>(relaxed = true)
    private val integrationRepository = mockk<IntegrationRepository>(relaxed = true)
    private val calendarSettingsRepository = mockk<CalendarSettingsRepository>(relaxed = true)
    private val backendApiClient = mockk<BackendApiClient>(relaxed = true)
    private val senderRuleRepository = mockk<SenderRuleRepository>(relaxed = true)
    private val emailFolderRepository = mockk<EmailFolderRepository>(relaxed = true)

    private fun viewModel() = SettingsViewModel(
        application, authRepository, integrationRepository, calendarSettingsRepository,
        backendApiClient, senderRuleRepository, emailFolderRepository
    )

    private fun setupMocks() {
        coEvery { authRepository.getCurrentUserEmail() } returns "test@example.com"
        coEvery { integrationRepository.fetchIntegrations() } returns IntegrationResult.Success(emptyList())
        every { backendApiClient.getGmailAuthUrl() } returns "https://example.com/auth"
        every { backendApiClient.getOutlookAuthUrl() } returns "https://example.com/outlook-auth"
        every { backendApiClient.getCalendarAuthUrl() } returns "https://example.com/calendar-auth"
        coEvery { calendarSettingsRepository.getSettings() } returns RepositoryResult.Success(null)
        coEvery { senderRuleRepository.fetchRules() } returns RepositoryResult.Success(emptyList())
        coEvery { backendApiClient.listCalendars() } returns Result.success(emptyList())
    }

    @Test
    fun settingsScreen_displaysTitle() {
        setupMocks()

        composeTestRule.setContent {
            SelkoTheme {
                SettingsScreen(
                    onLogout = {},
                    viewModel = viewModel()
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
                    viewModel = viewModel()
                )
            }
        }

        composeTestRule.waitForIdle()
        composeTestRule.onNodeWithText("Connected Accounts", ignoreCase = true).assertIsDisplayed()
    }

    @Test
    fun settingsScreen_showsCalendarDefaultsSection() {
        setupMocks()

        composeTestRule.setContent {
            SelkoTheme {
                SettingsScreen(
                    onLogout = {},
                    viewModel = viewModel()
                )
            }
        }

        composeTestRule.waitForIdle()
        composeTestRule.onNodeWithText("Calendar Defaults", ignoreCase = true).performScrollTo().assertIsDisplayed()
    }

    @Test
    fun settingsScreen_showsAccountSection() {
        setupMocks()

        composeTestRule.setContent {
            SelkoTheme {
                SettingsScreen(
                    onLogout = {},
                    viewModel = viewModel()
                )
            }
        }

        composeTestRule.waitForIdle()
        composeTestRule.onNodeWithText("Account", ignoreCase = true).performScrollTo().assertIsDisplayed()
    }

    @Test
    fun settingsScreen_showsLogOutButton() {
        setupMocks()

        composeTestRule.setContent {
            SelkoTheme {
                SettingsScreen(
                    onLogout = {},
                    viewModel = viewModel()
                )
            }
        }

        composeTestRule.waitForIdle()
        composeTestRule.onNodeWithText("Log out").performScrollTo().assertIsDisplayed()
    }

    @Test
    fun settingsScreen_showsUserEmail() {
        setupMocks()

        composeTestRule.setContent {
            SelkoTheme {
                SettingsScreen(
                    onLogout = {},
                    viewModel = viewModel()
                )
            }
        }

        composeTestRule.waitForIdle()
        composeTestRule.onNodeWithText("test@example.com").performScrollTo().assertIsDisplayed()
    }

    @Test
    fun settingsScreen_showsGmailIntegration() {
        setupMocks()

        composeTestRule.setContent {
            SelkoTheme {
                SettingsScreen(
                    onLogout = {},
                    viewModel = viewModel()
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
                    viewModel = viewModel()
                )
            }
        }

        composeTestRule.waitForIdle()
        composeTestRule.onNodeWithText("Google Calendar").assertIsDisplayed()
    }

    @Test
    fun settingsScreen_showsLabeledFolderSwitch_forConnectedProvider() {
        setupMocks()
        coEvery { integrationRepository.fetchIntegrations() } returns IntegrationResult.Success(listOf(
            Integration("integration-1", "user-1", IntegrationProvider.GMAIL, IntegrationStatus.ACTIVE, "test@example.com")
        ))
        coEvery { emailFolderRepository.list(IntegrationProvider.GMAIL) } returns RepositoryResult.Success(listOf(
            EmailFolderPreference(
                id = "folder-1", provider = "gmail", name = "Promotions",
                fullPath = "[Gmail]/Promotions", classificationDecision = "exclude",
                classificationReason = "Marketing messages", userOverride = false,
                isIncluded = false, isSystem = false
            )
        ))

        composeTestRule.setContent { SelkoTheme { SettingsScreen(onLogout = {}, viewModel = viewModel()) } }
        composeTestRule.waitForIdle()

        composeTestRule.onNodeWithText("[Gmail]/Promotions").assertIsDisplayed()
        composeTestRule.onNodeWithText("Excluded").assertIsDisplayed()
        composeTestRule.onAllNodes(isToggleable()).assertCountEquals(1)
    }
}
