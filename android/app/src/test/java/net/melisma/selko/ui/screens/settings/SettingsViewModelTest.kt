package net.melisma.selko.ui.screens.settings

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
import net.melisma.selko.data.api.BackendApiClient
import net.melisma.selko.data.model.SenderRule
import net.melisma.selko.data.repository.AuthRepository
import net.melisma.selko.data.repository.CalendarSettingsRepository
import net.melisma.selko.data.repository.IntegrationRepository
import net.melisma.selko.data.repository.IntegrationResult
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

    private lateinit var authRepository: AuthRepository
    private lateinit var integrationRepository: IntegrationRepository
    private lateinit var calendarSettingsRepository: CalendarSettingsRepository
    private lateinit var backendApiClient: BackendApiClient
    private lateinit var senderRuleRepository: SenderRuleRepository
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
        authRepository = mockk(relaxed = true)
        integrationRepository = mockk(relaxed = true)
        calendarSettingsRepository = mockk(relaxed = true)
        backendApiClient = mockk(relaxed = true)
        senderRuleRepository = mockk(relaxed = true)

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
            authRepository,
            integrationRepository,
            calendarSettingsRepository,
            backendApiClient,
            senderRuleRepository
        )
    }

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
}
