package net.melisma.selko.ui.screens.settings

import android.app.Application
import app.cash.turbine.test
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.mockk
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import net.melisma.selko.R
import net.melisma.selko.data.api.BackendApiClient
import net.melisma.selko.data.model.Integration
import net.melisma.selko.data.model.IntegrationProvider
import net.melisma.selko.data.model.IntegrationStatus
import net.melisma.selko.data.model.EmailFolderPreference
import net.melisma.selko.data.model.SenderRule
import net.melisma.selko.data.repository.AuthRepository
import net.melisma.selko.data.repository.CalendarSettingsRepository
import net.melisma.selko.data.repository.IntegrationRepository
import net.melisma.selko.data.repository.IntegrationResult
import net.melisma.selko.data.repository.EmailFolderRepository
import net.melisma.selko.data.repository.RepositoryResult
import net.melisma.selko.data.repository.SenderRuleRepository
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class SettingsViewModelTest {

    private lateinit var application: Application
    private lateinit var authRepository: AuthRepository
    private lateinit var integrationRepository: IntegrationRepository
    private lateinit var calendarSettingsRepository: CalendarSettingsRepository
    private lateinit var backendApiClient: BackendApiClient
    private lateinit var senderRuleRepository: SenderRuleRepository
    private lateinit var emailFolderRepository: EmailFolderRepository
    private lateinit var viewModel: SettingsViewModel
    private val testDispatcher = StandardTestDispatcher()

    private val testRules = listOf(
        SenderRule(
            id = "rule-1",
            userId = "user-1",
            senderEmail = "spam@example.com",
            action = "ignore",
            createdAt = "2026-01-01T00:00:00Z"
        ),
        SenderRule(
            id = "rule-2",
            userId = "user-1",
            senderDomain = "trusted.com",
            action = "auto_approve",
            createdAt = "2026-01-02T00:00:00Z"
        )
    )

    @Before
    fun setup() {
        Dispatchers.setMain(testDispatcher)
        application = mockk(relaxed = true)
        every { application.getString(R.string.settings_error_disconnect) } returns "Failed to disconnect"
        every { application.getString(R.string.settings_error_load_rules) } returns "Failed to load automation rules"
        every { application.getString(R.string.settings_error_create_rule) } returns "Failed to create rule"
        every { application.getString(R.string.settings_error_delete_rule) } returns "Failed to delete rule"
        every { application.getString(R.string.settings_error_save_calendar) } returns "Failed to save calendar settings"
        authRepository = mockk(relaxed = true)
        integrationRepository = mockk(relaxed = true)
        calendarSettingsRepository = mockk(relaxed = true)
        backendApiClient = mockk(relaxed = true)
        senderRuleRepository = mockk(relaxed = true)
        emailFolderRepository = mockk(relaxed = true)

        every { authRepository.getCurrentUserEmail() } returns "test@example.com"
        coEvery { integrationRepository.fetchIntegrations() } returns
                IntegrationResult.Success(emptyList())
        coEvery { calendarSettingsRepository.getSettings() } returns
                RepositoryResult.Success(null)
        coEvery { backendApiClient.listCalendars() } returns
                Result.success(emptyList())
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun createViewModel(): SettingsViewModel {
        return SettingsViewModel(
            application,
            authRepository,
            integrationRepository,
            calendarSettingsRepository,
            backendApiClient,
            senderRuleRepository,
            emailFolderRepository
        )
    }

    private fun folder(id: String = "folder-1", included: Boolean = false) = EmailFolderPreference(
        id = id,
        provider = "gmail",
        name = "Promotions",
        fullPath = "[Gmail]/Promotions",
        classificationDecision = "exclude",
        classificationReason = "Marketing messages",
        userOverride = false,
        isIncluded = included,
        isSystem = false
    )

    private val gmailIntegration = Integration(
        id = "integration-1",
        userId = "user-1",
        provider = IntegrationProvider.GMAIL,
        status = IntegrationStatus.ACTIVE,
        providerEmail = "test@example.com"
    )

    @Test
    fun `loadRules fetches and updates state`() = runTest {
        coEvery { senderRuleRepository.fetchRules() } returns RepositoryResult.Success(testRules)

        viewModel = createViewModel()
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.uiState.test {
            val state = awaitItem()
            assertEquals(2, state.rules.size)
            assertEquals("rule-1", state.rules[0].id)
            assertEquals("rule-2", state.rules[1].id)
            assertFalse(state.isLoadingRules)
        }
    }

    @Test
    fun `loadRules shows error on failure`() = runTest {
        coEvery { senderRuleRepository.fetchRules() } returns
                RepositoryResult.Error("Network error")

        viewModel = createViewModel()
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.uiState.test {
            val state = awaitItem()
            assertTrue(state.rules.isEmpty())
            assertEquals("Failed to load automation rules", state.errorMessage)
            assertFalse(state.isLoadingRules)
        }
    }

    @Test
    fun `createRule calls repository and reloads`() = runTest {
        val newRule = SenderRule(
            id = "rule-3",
            userId = "user-1",
            senderEmail = "new@example.com",
            action = "ignore",
            createdAt = "2026-01-03T00:00:00Z"
        )
        coEvery { senderRuleRepository.fetchRules() } returns RepositoryResult.Success(testRules)
        coEvery {
            senderRuleRepository.createRule("new@example.com", null, "ignore")
        } returns RepositoryResult.Success(newRule)

        viewModel = createViewModel()
        testDispatcher.scheduler.advanceUntilIdle()

        // After init, fetchRules has been called once
        coEvery { senderRuleRepository.fetchRules() } returns
                RepositoryResult.Success(testRules + newRule)

        viewModel.createRule("new@example.com", null, "ignore")
        testDispatcher.scheduler.advanceUntilIdle()

        coVerify { senderRuleRepository.createRule("new@example.com", null, "ignore") }
        // fetchRules called again after create
        coVerify(atLeast = 2) { senderRuleRepository.fetchRules() }
    }

    @Test
    fun `createRule shows error on failure`() = runTest {
        coEvery { senderRuleRepository.fetchRules() } returns RepositoryResult.Success(emptyList())
        coEvery {
            senderRuleRepository.createRule(any(), any(), any())
        } returns RepositoryResult.Error("Failed")

        viewModel = createViewModel()
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.createRule("test@example.com", null, "ignore")
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.uiState.test {
            val state = awaitItem()
            assertEquals("Failed to create rule", state.errorMessage)
        }
    }

    @Test
    fun `deleteRule calls repository and reloads`() = runTest {
        coEvery { senderRuleRepository.fetchRules() } returns RepositoryResult.Success(testRules)
        coEvery { senderRuleRepository.deleteRule("rule-1") } returns RepositoryResult.Success(Unit)

        viewModel = createViewModel()
        testDispatcher.scheduler.advanceUntilIdle()

        coEvery { senderRuleRepository.fetchRules() } returns
                RepositoryResult.Success(testRules.filter { it.id != "rule-1" })

        viewModel.deleteRule("rule-1")
        testDispatcher.scheduler.advanceUntilIdle()

        coVerify { senderRuleRepository.deleteRule("rule-1") }
        coVerify(atLeast = 2) { senderRuleRepository.fetchRules() }
    }

    @Test
    fun `deleteRule shows error on failure`() = runTest {
        coEvery { senderRuleRepository.fetchRules() } returns RepositoryResult.Success(testRules)
        coEvery { senderRuleRepository.deleteRule(any()) } returns
                RepositoryResult.Error("Failed")

        viewModel = createViewModel()
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.deleteRule("rule-1")
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.uiState.test {
            val state = awaitItem()
            assertEquals("Failed to delete rule", state.errorMessage)
        }
    }

    @Test
    fun `rules are loaded on init`() = runTest {
        coEvery { senderRuleRepository.fetchRules() } returns RepositoryResult.Success(testRules)

        viewModel = createViewModel()
        testDispatcher.scheduler.advanceUntilIdle()

        coVerify(exactly = 1) { senderRuleRepository.fetchRules() }
    }

    @Test
    fun `saveCalendarSettings shows error on failure`() = runTest {
        coEvery { senderRuleRepository.fetchRules() } returns RepositoryResult.Success(emptyList())
        coEvery {
            calendarSettingsRepository.updateSettings(any(), any())
        } returns RepositoryResult.Error("Save failed")

        viewModel = createViewModel()
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.saveCalendarSettings()
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.uiState.test {
            val state = awaitItem()
            assertEquals("Failed to save calendar settings", state.errorMessage)
            assertFalse(state.isSavingCalendarSettings)
        }
    }

    @Test
    fun `connected email folders load and remain provider scoped`() = runTest {
        coEvery { integrationRepository.fetchIntegrations() } returns IntegrationResult.Success(listOf(gmailIntegration))
        coEvery { emailFolderRepository.list(IntegrationProvider.GMAIL) } returns RepositoryResult.Success(listOf(folder()))
        coEvery { senderRuleRepository.fetchRules() } returns RepositoryResult.Success(emptyList())

        viewModel = createViewModel()
        testDispatcher.scheduler.advanceUntilIdle()

        assertEquals(1, viewModel.uiState.value.emailFolders[IntegrationProvider.GMAIL]?.size)
        assertTrue(viewModel.uiState.value.emailFolders[IntegrationProvider.OUTLOOK].isNullOrEmpty())
        coVerify(exactly = 1) { emailFolderRepository.list(IntegrationProvider.GMAIL) }
    }

    @Test
    fun `folder update is optimistic and only the changed row is busy`() = runTest {
        val second = folder("folder-2", true)
        coEvery { integrationRepository.fetchIntegrations() } returns IntegrationResult.Success(listOf(gmailIntegration))
        coEvery { emailFolderRepository.list(IntegrationProvider.GMAIL) } returns RepositoryResult.Success(listOf(folder(), second))
        coEvery { emailFolderRepository.update(IntegrationProvider.GMAIL, "folder-1", true) } coAnswers {
            kotlinx.coroutines.delay(100)
            RepositoryResult.Success(folder(included = true))
        }
        coEvery { senderRuleRepository.fetchRules() } returns RepositoryResult.Success(emptyList())
        viewModel = createViewModel()
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.updateEmailFolder(IntegrationProvider.GMAIL, "folder-1", true)
        testDispatcher.scheduler.runCurrent()
        assertTrue(viewModel.uiState.value.emailFolders.getValue(IntegrationProvider.GMAIL).first().isIncluded)
        assertEquals(setOf("folder-1"), viewModel.uiState.value.updatingFolderIds)

        testDispatcher.scheduler.advanceUntilIdle()
        assertTrue(viewModel.uiState.value.updatingFolderIds.isEmpty())
    }

    @Test
    fun `failed folder update rolls back and retry applies requested value`() = runTest {
        coEvery { integrationRepository.fetchIntegrations() } returns IntegrationResult.Success(listOf(gmailIntegration))
        coEvery { emailFolderRepository.list(IntegrationProvider.GMAIL) } returns RepositoryResult.Success(listOf(folder()))
        coEvery { senderRuleRepository.fetchRules() } returns RepositoryResult.Success(emptyList())
        coEvery { emailFolderRepository.update(IntegrationProvider.GMAIL, "folder-1", true) } returns RepositoryResult.Error("Save failed")
        viewModel = createViewModel()
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.updateEmailFolder(IntegrationProvider.GMAIL, "folder-1", true)
        testDispatcher.scheduler.advanceUntilIdle()
        assertFalse(viewModel.uiState.value.emailFolders.getValue(IntegrationProvider.GMAIL).first().isIncluded)
        assertEquals("Save failed", viewModel.uiState.value.folderUpdateErrors["folder-1"]?.message)

        coEvery { emailFolderRepository.update(IntegrationProvider.GMAIL, "folder-1", true) } returns RepositoryResult.Success(folder(included = true))
        viewModel.retryEmailFolder(IntegrationProvider.GMAIL, "folder-1")
        testDispatcher.scheduler.advanceUntilIdle()
        assertTrue(viewModel.uiState.value.emailFolders.getValue(IntegrationProvider.GMAIL).first().isIncluded)
        assertFalse(viewModel.uiState.value.folderUpdateErrors.containsKey("folder-1"))
    }
}
