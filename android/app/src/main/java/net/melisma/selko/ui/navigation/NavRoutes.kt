package net.melisma.selko.ui.navigation

import kotlinx.serialization.Serializable

@Serializable
object Auth

@Serializable
object Home

@Serializable
object Review

@Serializable
object History

@Serializable
object Settings

@Serializable
data class EventDetail(val eventId: String)
