package net.melisma.selko.di

import net.melisma.selko.data.api.BackendApiClient
import net.melisma.selko.data.api.createSupabaseClient
import net.melisma.selko.data.repository.AuthRepository
import net.melisma.selko.data.repository.CalendarSettingsRepository
import net.melisma.selko.data.repository.EmailRepository
import net.melisma.selko.data.repository.EventRepository
import net.melisma.selko.data.repository.IntegrationRepository
import net.melisma.selko.data.repository.SenderRuleRepository
import net.melisma.selko.ui.screens.auth.AuthViewModel
import net.melisma.selko.ui.screens.history.HistoryViewModel
import net.melisma.selko.ui.screens.home.HomeViewModel
import net.melisma.selko.ui.screens.review.EventDetailViewModel
import net.melisma.selko.ui.screens.review.ReviewQueueViewModel
import net.melisma.selko.ui.screens.settings.SettingsViewModel
import org.koin.core.module.dsl.viewModel
import org.koin.dsl.module

val appModule = module {
    // Supabase Client
    single { createSupabaseClient() }

    // Backend API Client (for server-side operations)
    single { BackendApiClient(get()) }

    // Repositories
    single { AuthRepository(get()) }
    single { EmailRepository(get()) }
    single { EventRepository(get()) }
    single { IntegrationRepository(get()) }
    single { CalendarSettingsRepository(get()) }
    single { SenderRuleRepository(get()) }

    // ViewModels
    viewModel { AuthViewModel(get()) }
    viewModel { HomeViewModel(get()) }
    viewModel { ReviewQueueViewModel(get(), get(), get(), get()) }
    viewModel { (eventId: String) -> EventDetailViewModel(get(), eventId) }
    viewModel { HistoryViewModel(get(), get()) }
    viewModel { SettingsViewModel(get(), get(), get(), get(), get()) }
}
