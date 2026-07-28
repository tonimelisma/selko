package net.melisma.selko.data.api

import kotlinx.serialization.json.Json
import net.melisma.selko.data.model.EmailFolderPreference
import net.melisma.selko.data.model.IntegrationProvider
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class BackendApiFolderContractTest {
    @Test
    fun `oauth paths support active providers but not parked photos`() {
        assertEquals(
            "/integrations/gmail/auth",
            BackendApiClient.oauthPath(IntegrationProvider.GMAIL)
        )
        assertEquals(
            "/integrations/outlook/auth",
            BackendApiClient.oauthPath(IntegrationProvider.OUTLOOK)
        )
        assertEquals(
            "/integrations/calendar/auth",
            BackendApiClient.oauthPath(IntegrationProvider.GOOGLE_CALENDAR)
        )
        assertNull(BackendApiClient.oauthPath(IntegrationProvider.GOOGLE_PHOTOS))
    }

    @Test
    fun `folder paths restrict providers and encode opaque ids`() {
        assertEquals("/integrations/gmail/folders", BackendApiClient.emailFolderPath("gmail"))
        assertEquals(
            "/integrations/outlook/folders/A%2FB%2BC%3D%3D",
            BackendApiClient.emailFolderPath("outlook", "A/B+C==")
        )
        assertNull(BackendApiClient.emailFolderPath("calendar"))
    }

    @Test
    fun `folder response decodes existing backend contract`() {
        val json = """{"id":"row-1","provider":"gmail","name":"Promotions","full_path":"[Gmail]/Promotions","classification_decision":"exclude","classification_reason":"Marketing","user_override":false,"is_included":false,"is_system":false}"""
        val folder = Json.decodeFromString<EmailFolderPreference>(json)
        assertEquals("[Gmail]/Promotions", folder.fullPath)
        assertEquals("exclude", folder.classificationDecision)
        assertEquals(false, folder.isIncluded)
    }
}
