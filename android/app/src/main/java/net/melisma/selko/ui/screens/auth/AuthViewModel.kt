package net.melisma.selko.ui.screens.auth

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import net.melisma.selko.R
import net.melisma.selko.data.repository.AuthRepository
import net.melisma.selko.data.repository.AuthResult

data class AuthUiState(
    val email: String = "",
    val password: String = "",
    val confirmPassword: String = "",
    val isSignUp: Boolean = false,
    val isLoading: Boolean = false,
    val errorMessage: String? = null,
    val isSuccess: Boolean = false
)

class AuthViewModel(
    application: Application,
    private val authRepository: AuthRepository
) : AndroidViewModel(application) {

    private val _uiState = MutableStateFlow(AuthUiState())
    val uiState: StateFlow<AuthUiState> = _uiState.asStateFlow()

    private fun getString(resId: Int): String = getApplication<Application>().getString(resId)

    fun onEmailChange(email: String) {
        _uiState.update { it.copy(email = email, errorMessage = null) }
    }

    fun onPasswordChange(password: String) {
        _uiState.update { it.copy(password = password, errorMessage = null) }
    }

    fun onConfirmPasswordChange(confirmPassword: String) {
        _uiState.update { it.copy(confirmPassword = confirmPassword, errorMessage = null) }
    }

    fun toggleAuthMode() {
        _uiState.update { it.copy(isSignUp = !it.isSignUp, confirmPassword = "", errorMessage = null) }
    }

    fun clearError() {
        _uiState.update { it.copy(errorMessage = null) }
    }

    fun submit() {
        val state = _uiState.value
        if (state.email.isBlank() || state.password.isBlank()) {
            _uiState.update { it.copy(errorMessage = getString(R.string.auth_error_email_password_required)) }
            return
        }

        if (state.isSignUp) {
            if (state.confirmPassword.isBlank()) {
                _uiState.update { it.copy(errorMessage = getString(R.string.auth_error_confirm_password)) }
                return
            }
            if (state.password != state.confirmPassword) {
                _uiState.update { it.copy(errorMessage = getString(R.string.auth_error_passwords_mismatch)) }
                return
            }
        }

        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, errorMessage = null) }

            val result = if (state.isSignUp) {
                authRepository.signUp(state.email, state.password)
            } else {
                authRepository.signIn(state.email, state.password)
            }

            when (result) {
                is AuthResult.Success -> {
                    _uiState.update { it.copy(isLoading = false, isSuccess = true) }
                }
                is AuthResult.Error -> {
                    _uiState.update { it.copy(isLoading = false, errorMessage = result.message) }
                }
            }
        }
    }
}
