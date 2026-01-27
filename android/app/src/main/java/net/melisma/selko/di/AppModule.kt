package net.melisma.selko.di

import net.melisma.selko.data.api.SupabaseAuthApi
import net.melisma.selko.data.api.createHttpClient
import net.melisma.selko.data.repository.AuthRepository
import net.melisma.selko.data.repository.TokenStorage
import net.melisma.selko.ui.screens.auth.AuthViewModel
import net.melisma.selko.ui.screens.home.HomeViewModel
import org.koin.android.ext.koin.androidContext
import org.koin.core.module.dsl.viewModel
import org.koin.dsl.module

val appModule = module {
    // HTTP Client
    single { createHttpClient() }

    // API
    single { SupabaseAuthApi(get()) }

    // Storage
    single { TokenStorage(androidContext()) }

    // Repository
    single { AuthRepository(get(), get()) }

    // ViewModels
    viewModel { AuthViewModel(get()) }
    viewModel { HomeViewModel(get()) }
}
