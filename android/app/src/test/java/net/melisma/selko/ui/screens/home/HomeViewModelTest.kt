package net.melisma.selko.ui.screens.home

import app.cash.turbine.test
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.mockk
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import net.melisma.selko.data.repository.AuthRepository
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class HomeViewModelTest {

    private lateinit var authRepository: AuthRepository
    private lateinit var viewModel: HomeViewModel
    private val testDispatcher = StandardTestDispatcher()
    private val userEmailFlow = MutableStateFlow<String?>(null)

    @Before
    fun setup() {
        Dispatchers.setMain(testDispatcher)
        authRepository = mockk(relaxed = true)
        every { authRepository.userEmail } returns userEmailFlow
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun `initial state has null email`() = runTest {
        viewModel = HomeViewModel(authRepository)
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.uiState.test {
            val state = awaitItem()
            assertNull(state.userEmail)
            assertFalse(state.isLoggingOut)
        }
    }

    @Test
    fun `state updates when user email changes`() = runTest {
        viewModel = HomeViewModel(authRepository)
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.uiState.test {
            // Initial state
            val initialState = awaitItem()
            assertNull(initialState.userEmail)

            // Update email
            userEmailFlow.value = "test@example.com"
            testDispatcher.scheduler.advanceUntilIdle()

            val updatedState = awaitItem()
            assertEquals("test@example.com", updatedState.userEmail)
        }
    }

    @Test
    fun `state shows email from repository on init`() = runTest {
        userEmailFlow.value = "existing@example.com"
        viewModel = HomeViewModel(authRepository)
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.uiState.test {
            val state = awaitItem()
            assertEquals("existing@example.com", state.userEmail)
        }
    }

    @Test
    fun `logout sets isLoggingOut to true`() = runTest {
        coEvery { authRepository.signOut() } coAnswers {
            // Simulate some delay
        }

        viewModel = HomeViewModel(authRepository)
        testDispatcher.scheduler.advanceUntilIdle()

        var callbackCalled = false

        viewModel.uiState.test {
            skipItems(1) // Skip initial state

            viewModel.logout { callbackCalled = true }

            val loggingOutState = awaitItem()
            assertTrue(loggingOutState.isLoggingOut)

            testDispatcher.scheduler.advanceUntilIdle()
        }
    }

    @Test
    fun `logout calls repository signOut`() = runTest {
        viewModel = HomeViewModel(authRepository)
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.logout { }
        testDispatcher.scheduler.advanceUntilIdle()

        coVerify { authRepository.signOut() }
    }

    @Test
    fun `logout callback is called after signOut completes`() = runTest {
        viewModel = HomeViewModel(authRepository)
        testDispatcher.scheduler.advanceUntilIdle()

        var callbackCalled = false
        viewModel.logout { callbackCalled = true }
        testDispatcher.scheduler.advanceUntilIdle()

        assertTrue(callbackCalled)
    }

    @Test
    fun `email updates are reflected in state`() = runTest {
        viewModel = HomeViewModel(authRepository)
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.uiState.test {
            // Initial state
            awaitItem()

            // Multiple email updates
            userEmailFlow.value = "first@example.com"
            testDispatcher.scheduler.advanceUntilIdle()
            assertEquals("first@example.com", awaitItem().userEmail)

            userEmailFlow.value = "second@example.com"
            testDispatcher.scheduler.advanceUntilIdle()
            assertEquals("second@example.com", awaitItem().userEmail)

            // Set to null (logged out)
            userEmailFlow.value = null
            testDispatcher.scheduler.advanceUntilIdle()
            assertNull(awaitItem().userEmail)
        }
    }
}
