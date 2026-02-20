package net.melisma.selko.data.repository

import net.melisma.selko.data.model.SenderRule
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Unit tests for SenderRule model.
 *
 * Note: Full SenderRuleRepository testing requires instrumented tests or integration tests
 * because the Supabase SDK uses extension functions that are difficult to mock in unit tests.
 * The ViewModel tests cover the repository interaction through mocking at that level.
 */
class SenderRuleRepositoryTest {

    @Test
    fun `SenderRule with email has correct properties`() {
        val rule = SenderRule(
            id = "rule-1",
            userId = "user-1",
            senderEmail = "test@example.com",
            senderDomain = null,
            action = "ignore",
            createdAt = "2026-01-01T00:00:00Z"
        )

        assertEquals("rule-1", rule.id)
        assertEquals("user-1", rule.userId)
        assertEquals("test@example.com", rule.senderEmail)
        assertNull(rule.senderDomain)
        assertEquals("ignore", rule.action)
        assertEquals("2026-01-01T00:00:00Z", rule.createdAt)
    }

    @Test
    fun `SenderRule with domain has correct properties`() {
        val rule = SenderRule(
            id = "rule-2",
            userId = "user-1",
            senderEmail = null,
            senderDomain = "example.com",
            action = "auto_approve",
            createdAt = "2026-01-01T00:00:00Z"
        )

        assertEquals("rule-2", rule.id)
        assertEquals("user-1", rule.userId)
        assertNull(rule.senderEmail)
        assertEquals("example.com", rule.senderDomain)
        assertEquals("auto_approve", rule.action)
    }

    @Test
    fun `SenderRule instances are equal with same values`() {
        val rule1 = SenderRule(
            id = "rule-1",
            userId = "user-1",
            senderEmail = "test@example.com",
            senderDomain = null,
            action = "ignore",
            createdAt = "2026-01-01T00:00:00Z"
        )
        val rule2 = SenderRule(
            id = "rule-1",
            userId = "user-1",
            senderEmail = "test@example.com",
            senderDomain = null,
            action = "ignore",
            createdAt = "2026-01-01T00:00:00Z"
        )

        assertEquals(rule1, rule2)
    }

    @Test
    fun `SenderRule can have both email and domain null`() {
        val rule = SenderRule(
            id = "rule-3",
            userId = "user-1",
            senderEmail = null,
            senderDomain = null,
            action = "ignore",
            createdAt = "2026-01-01T00:00:00Z"
        )

        assertNull(rule.senderEmail)
        assertNull(rule.senderDomain)
    }

    @Test
    fun `SenderRule action values are valid strings`() {
        val ignoreRule = SenderRule(
            id = "rule-1",
            userId = "user-1",
            senderEmail = "test@example.com",
            action = "ignore",
            createdAt = "2026-01-01T00:00:00Z"
        )
        val autoApproveRule = SenderRule(
            id = "rule-2",
            userId = "user-1",
            senderEmail = "test@example.com",
            action = "auto_approve",
            createdAt = "2026-01-01T00:00:00Z"
        )

        assertTrue(ignoreRule.action == "ignore")
        assertTrue(autoApproveRule.action == "auto_approve")
    }
}
