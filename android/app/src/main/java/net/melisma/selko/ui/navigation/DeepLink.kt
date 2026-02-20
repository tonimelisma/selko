package net.melisma.selko.ui.navigation

import android.net.Uri

/**
 * Sealed class representing deep link targets for the Selko app.
 * Supported URL schemes:
 * - selko://review -> Review tab
 * - selko://history -> History tab
 * - selko://settings -> Settings tab
 * - selko://event/{id} -> Event detail screen
 */
sealed class DeepLink {
    data object ReviewTab : DeepLink()
    data object HistoryTab : DeepLink()
    data object SettingsTab : DeepLink()
    data class EventDetail(val eventId: String) : DeepLink()
}

/**
 * Parses a [Uri] into a [DeepLink] target.
 * Returns null if the URI does not match any known deep link pattern.
 */
fun parseDeepLink(uri: Uri?): DeepLink? {
    if (uri == null) return null
    return parseDeepLink(uri.toString())
}

/**
 * Parses a URI string into a [DeepLink] target.
 * Returns null if the URI does not match any known deep link pattern.
 *
 * This overload is suitable for unit testing without Android framework dependencies.
 */
fun parseDeepLink(uriString: String?): DeepLink? {
    if (uriString.isNullOrBlank()) return null

    // Must start with selko:// scheme
    if (!uriString.startsWith("selko://")) return null

    // Extract the part after "selko://"
    val path = uriString.removePrefix("selko://")

    // Remove query parameters and fragment
    val cleanPath = path.split("?").first().split("#").first()

    // Split into segments
    val segments = cleanPath.split("/").filter { it.isNotBlank() }

    if (segments.isEmpty()) return null

    return when (segments[0]) {
        "review" -> DeepLink.ReviewTab
        "history" -> DeepLink.HistoryTab
        "settings" -> DeepLink.SettingsTab
        "event" -> {
            val eventId = segments.getOrNull(1)
            if (eventId.isNullOrBlank()) null else DeepLink.EventDetail(eventId)
        }
        else -> null
    }
}
