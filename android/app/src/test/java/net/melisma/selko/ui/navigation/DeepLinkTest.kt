package net.melisma.selko.ui.navigation

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DeepLinkTest {

    @Test
    fun `parseDeepLink returns null for null string`() {
        val result = parseDeepLink(null as String?)
        assertNull(result)
    }

    @Test
    fun `parseDeepLink returns null for empty string`() {
        val result = parseDeepLink("")
        assertNull(result)
    }

    @Test
    fun `parseDeepLink returns null for blank string`() {
        val result = parseDeepLink("   ")
        assertNull(result)
    }

    @Test
    fun `parseDeepLink returns null for non-selko scheme`() {
        val result = parseDeepLink("https://example.com/review")
        assertNull(result)
    }

    @Test
    fun `parseDeepLink returns null for http scheme`() {
        val result = parseDeepLink("http://review")
        assertNull(result)
    }

    @Test
    fun `parseDeepLink returns ReviewTab for selko review`() {
        val result = parseDeepLink("selko://review")
        assertTrue(result is DeepLink.ReviewTab)
    }

    @Test
    fun `parseDeepLink returns HistoryTab for selko history`() {
        val result = parseDeepLink("selko://history")
        assertTrue(result is DeepLink.HistoryTab)
    }

    @Test
    fun `parseDeepLink returns SettingsTab for selko settings`() {
        val result = parseDeepLink("selko://settings")
        assertTrue(result is DeepLink.SettingsTab)
    }

    @Test
    fun `parseDeepLink returns EventDetail for selko event with id`() {
        val result = parseDeepLink("selko://event/abc-123")
        assertTrue(result is DeepLink.EventDetail)
        assertEquals("abc-123", (result as DeepLink.EventDetail).eventId)
    }

    @Test
    fun `parseDeepLink returns EventDetail with uuid`() {
        val result = parseDeepLink("selko://event/550e8400-e29b-41d4-a716-446655440000")
        assertTrue(result is DeepLink.EventDetail)
        assertEquals(
            "550e8400-e29b-41d4-a716-446655440000",
            (result as DeepLink.EventDetail).eventId
        )
    }

    @Test
    fun `parseDeepLink returns null for event without id`() {
        val result = parseDeepLink("selko://event")
        assertNull(result)
    }

    @Test
    fun `parseDeepLink returns null for event with trailing slash and no id`() {
        val result = parseDeepLink("selko://event/")
        assertNull(result)
    }

    @Test
    fun `parseDeepLink returns null for unknown host`() {
        val result = parseDeepLink("selko://unknown")
        assertNull(result)
    }

    @Test
    fun `parseDeepLink ignores extra path segments for tab routes`() {
        val result = parseDeepLink("selko://review/extra/path")
        assertTrue(result is DeepLink.ReviewTab)
    }

    @Test
    fun `parseDeepLink handles event with query parameters`() {
        val result = parseDeepLink("selko://event/abc-123?source=notification")
        assertTrue(result is DeepLink.EventDetail)
        assertEquals("abc-123", (result as DeepLink.EventDetail).eventId)
    }

    @Test
    fun `parseDeepLink handles event with fragment`() {
        val result = parseDeepLink("selko://event/abc-123#section")
        assertTrue(result is DeepLink.EventDetail)
        assertEquals("abc-123", (result as DeepLink.EventDetail).eventId)
    }

    @Test
    fun `parseDeepLink returns null for selko scheme with no path`() {
        val result = parseDeepLink("selko://")
        assertNull(result)
    }
}
