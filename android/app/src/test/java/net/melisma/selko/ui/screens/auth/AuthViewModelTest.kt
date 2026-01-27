package net.melisma.selko.ui.screens.auth

import app.cash.turbine.test
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import net.melisma.selko.data.repository.AuthRepository
import net.melisma.selko.data.repository.AuthResult
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class AuthViewModelTest {

    private lateinit var authRepository: AuthRepository
    private lateinit var viewModel: AuthViewModel
    private val testDispatcher = StandardTestDispatcher()

    @Before
    fun setup() {
        Dispatchers.setMain(testDispatcher)
        authRepository = mockk(relaxed = true)
        viewModel = AuthViewModel(authRepository)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun `initial state is correct`() = runTest {
        viewModel.uiState.test {
            val state = awaitItem()
            assertEquals("", state.email)
            assertEquals("", state.password)
            assertFalse(state.isSignUp)
            assertFalse(state.isLoading)
            assertNull(state.errorMessage)
            assertFalse(state.isSuccess)
        }
    }

    @Test
    fun `onEmailChange updates email in state`() = runTest {
        viewModel.uiState.test {
            skipItems(1) // Skip initial state

            viewModel.onEmailChange("test@example.com")

            val state = awaitItem()
            assertEquals("test@example.com", state.email)
        }
    }

    @Test
    fun `onEmailChange clears error message`() = runTest {
        // First trigger an error
        viewModel.submit()
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.uiState.test {
            val errorState = awaitItem()
            assertEquals("Email and password are required", errorState.errorMessage)

            viewModel.onEmailChange("test@example.com")

            val clearedState = awaitItem()
            assertNull(clearedState.errorMessage)
        }
    }

    @Test
    fun `onPasswordChange updates password in state`() = runTest {
        viewModel.uiState.test {
            skipItems(1) // Skip initial state

            viewModel.onPasswordChange("password123")

            val state = awaitItem()
            assertEquals("password123", state.password)
        }
    }

    @Test
    fun `onPasswordChange clears error message`() = runTest {
        // First trigger an error
        viewModel.submit()
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.uiState.test {
            val errorState = awaitItem()
            assertEquals("Email and password are required", errorState.errorMessage)

            viewModel.onPasswordChange("password123")

            val clearedState = awaitItem()
            assertNull(clearedState.errorMessage)
        }
    }

    @Test
    fun `toggleAuthMode switches between login and signup`() = runTest {
        viewModel.uiState.test {
            val initialState = awaitItem()
            assertFalse(initialState.isSignUp)

            viewModel.toggleAuthMode()

            val toggledState = awaitItem()
            assertTrue(toggledState.isSignUp)

            viewModel.toggleAuthMode()

            val toggledBackState = awaitItem()
            assertFalse(toggledBackState.isSignUp)
        }
    }

    @Test
    fun `toggleAuthMode clears error message`() = runTest {
        // First trigger an error
        viewModel.submit()
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.uiState.test {
            val errorState = awaitItem()
            assertEquals("Email and password are required", errorState.errorMessage)

            viewModel.toggleAuthMode()

            val clearedState = awaitItem()
            assertNull(clearedState.errorMessage)
        }
    }

    @Test
    fun `clearError removes error message`() = runTest {
        // First trigger an error
        viewModel.submit()
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.uiState.test {
            val errorState = awaitItem()
            assertEquals("Email and password are required", errorState.errorMessage)

            viewModel.clearError()

            val clearedState = awaitItem()
            assertNull(clearedState.errorMessage)
        }
    }

    @Test
    fun `submit with empty email shows error`() = runTest {
        viewModel.onPasswordChange("password123")
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.uiState.test {
            skipItems(1) // Skip password change state

            viewModel.submit()
            testDispatcher.scheduler.advanceUntilIdle()

            val errorState = awaitItem()
            assertEquals("Email and password are required", errorState.errorMessage)
            assertFalse(errorState.isLoading)
        }
    }

    @Test
    fun `submit with empty password shows error`() = runTest {
        viewModel.onEmailChange("test@example.com")
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.uiState.test {
            skipItems(1) // Skip email change state

            viewModel.submit()
            testDispatcher.scheduler.advanceUntilIdle()

            val errorState = awaitItem()
            assertEquals("Email and password are required", errorState.errorMessage)
            assertFalse(errorState.isLoading)
        }
    }

    @Test
    fun `submit with blank email shows error`() = runTest {
        viewModel.onEmailChange("   ")
        viewModel.onPasswordChange("password123")
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.uiState.test {
            skipItems(1) // Skip previous state changes

            viewModel.submit()
            testDispatcher.scheduler.advanceUntilIdle()

            val errorState = awaitItem()
            assertEquals("Email and password are required", errorState.errorMessage)
        }
    }

    @Test
    fun `submit signIn success updates state correctly`() = runTest {
        coEvery { authRepository.signIn(any(), any()) } returns AuthResult.Success("test@example.com")

        viewModel.onEmailChange("test@example.com")
        viewModel.onPasswordChange("password123")
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.uiState.test {
            skipItems(1) // Skip input changes

            viewModel.submit()

            val loadingState = awaitItem()
            assertTrue(loadingState.isLoading)
            assertNull(loadingState.errorMessage)

            testDispatcher.scheduler.advanceUntilIdle()

            val successState = awaitItem()
            assertFalse(successState.isLoading)
            assertTrue(successState.isSuccess)
        }

        coVerify { authRepository.signIn("test@example.com", "password123") }
    }

    @Test
    fun `submit signUp success updates state correctly`() = runTest {
        coEvery { authRepository.signUp(any(), any()) } returns AuthResult.Success("test@example.com")

        viewModel.toggleAuthMode() // Switch to signup
        viewModel.onEmailChange("test@example.com")
        viewModel.onPasswordChange("password123")
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.uiState.test {
            skipItems(1) // Skip input changes

            viewModel.submit()

            val loadingState = awaitItem()
            assertTrue(loadingState.isLoading)

            testDispatcher.scheduler.advanceUntilIdle()

            val successState = awaitItem()
            assertFalse(successState.isLoading)
            assertTrue(successState.isSuccess)
        }

        coVerify { authRepository.signUp("test@example.com", "password123") }
    }

    @Test
    fun `submit signIn failure shows error`() = runTest {
        coEvery { authRepository.signIn(any(), any()) } returns AuthResult.Error("Invalid credentials")

        viewModel.onEmailChange("test@example.com")
        viewModel.onPasswordChange("wrongpassword")
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.uiState.test {
            skipItems(1) // Skip input changes

            viewModel.submit()

            val loadingState = awaitItem()
            assertTrue(loadingState.isLoading)

            testDispatcher.scheduler.advanceUntilIdle()

            val errorState = awaitItem()
            assertFalse(errorState.isLoading)
            assertFalse(errorState.isSuccess)
            assertEquals("Invalid credentials", errorState.errorMessage)
        }
    }

    @Test
    fun `submit signUp failure shows error`() = runTest {
        coEvery { authRepository.signUp(any(), any()) } returns AuthResult.Error("Email already registered")

        viewModel.toggleAuthMode() // Switch to signup
        viewModel.onEmailChange("existing@example.com")
        viewModel.onPasswordChange("password123")
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.uiState.test {
            skipItems(1) // Skip input changes

            viewModel.submit()

            val loadingState = awaitItem()
            assertTrue(loadingState.isLoading)

            testDispatcher.scheduler.advanceUntilIdle()

            val errorState = awaitItem()
            assertFalse(errorState.isLoading)
            assertFalse(errorState.isSuccess)
            assertEquals("Email already registered", errorState.errorMessage)
        }
    }

    @Test
    fun `submit does not call repository when validation fails`() = runTest {
        viewModel.submit()
        testDispatcher.scheduler.advanceUntilIdle()

        coVerify(exactly = 0) { authRepository.signIn(any(), any()) }
        coVerify(exactly = 0) { authRepository.signUp(any(), any()) }
    }

    @Test
    fun `state preserves email and password after failed submit`() = runTest {
        coEvery { authRepository.signIn(any(), any()) } returns AuthResult.Error("Network error")

        viewModel.onEmailChange("test@example.com")
        viewModel.onPasswordChange("password123")
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.submit()
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.uiState.test {
            val state = awaitItem()
            assertEquals("test@example.com", state.email)
            assertEquals("password123", state.password)
            assertEquals("Network error", state.errorMessage)
        }
    }
}
