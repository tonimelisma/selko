package net.melisma.selko.data.repository

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Unit tests for AuthResult sealed class.
 *
 * Note: Full AuthRepository testing requires instrumented tests or integration tests
 * because the Supabase SDK uses extension functions that are difficult to mock in unit tests.
 * The ViewModel tests already cover the repository interaction through mocking at that level.
 */
class AuthRepositoryTest {

    @Test
    fun `AuthResult Success contains email`() {
        val result = AuthResult.Success("test@example.com")

        assertTrue(result is AuthResult.Success)
        assertEquals("test@example.com", result.email)
    }

    @Test
    fun `AuthResult Success can have null email`() {
        val result = AuthResult.Success(null)

        assertTrue(result is AuthResult.Success)
        assertNull(result.email)
    }

    @Test
    fun `AuthResult Error contains message`() {
        val result = AuthResult.Error("Invalid credentials")

        assertTrue(result is AuthResult.Error)
        assertEquals("Invalid credentials", result.message)
    }

    @Test
    fun `AuthResult Error can have empty message`() {
        val result = AuthResult.Error("")

        assertTrue(result is AuthResult.Error)
        assertEquals("", result.message)
    }

    @Test
    fun `AuthResult sealed class exhaustive when check`() {
        val successResult: AuthResult = AuthResult.Success("test@example.com")
        val errorResult: AuthResult = AuthResult.Error("Error message")

        // Verify exhaustive when works
        val successMessage = when (successResult) {
            is AuthResult.Success -> "Success: ${successResult.email}"
            is AuthResult.Error -> "Error: ${successResult.message}"
        }
        assertEquals("Success: test@example.com", successMessage)

        val errorMessage = when (errorResult) {
            is AuthResult.Success -> "Success: ${errorResult.email}"
            is AuthResult.Error -> "Error: ${errorResult.message}"
        }
        assertEquals("Error: Error message", errorMessage)
    }

    @Test
    fun `AuthResult Success instances are equal with same email`() {
        val result1 = AuthResult.Success("test@example.com")
        val result2 = AuthResult.Success("test@example.com")

        assertEquals(result1, result2)
    }

    @Test
    fun `AuthResult Error instances are equal with same message`() {
        val result1 = AuthResult.Error("Error message")
        val result2 = AuthResult.Error("Error message")

        assertEquals(result1, result2)
    }
}
