package net.melisma.selko.di

import net.melisma.selko.data.api.BackendApiClient
import net.melisma.selko.data.api.createSupabaseClient
import net.melisma.selko.data.repository.AuthRepository
import net.melisma.selko.data.repository.EmailRepository
import net.melisma.selko.data.repository.EventRepository
import net.melisma.selko.data.repository.IntegrationRepository
import net.melisma.selko.ui.screens.auth.AuthViewModel
import net.melisma.selko.ui.screens.home.HomeViewModel
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

    // ViewModels
    viewModel { AuthViewModel(get()) }
    viewModel { HomeViewModel(get()) }
}
