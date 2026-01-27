package net.melisma.selko.di

import net.melisma.selko.data.api.createSupabaseClient
import net.melisma.selko.data.repository.AuthRepository
import net.melisma.selko.ui.screens.auth.AuthViewModel
import net.melisma.selko.ui.screens.home.HomeViewModel
import org.koin.core.module.dsl.viewModel
import org.koin.dsl.module

val appModule = module {
    // Supabase Client
    single { createSupabaseClient() }

    // Repository
    single { AuthRepository(get()) }

    // ViewModels
    viewModel { AuthViewModel(get()) }
    viewModel { HomeViewModel(get()) }
}
