<script>
	import { _ } from 'svelte-i18n';
	import { supabase } from '$lib/supabase.js';
	import ErrorAlert from '$lib/components/ErrorAlert.svelte';

	let email = $state('');
	let password = $state('');
	let confirmPassword = $state('');
	let error = $state('');
	let success = $state(false);
	let isLoading = $state(false);

	/** @param {SubmitEvent} event */
	async function handleRegister(event) {
		event.preventDefault();
		error = '';

		if (password !== confirmPassword) {
			error = $_('auth.passwordMismatch');
			return;
		}

		if (password.length < 6) {
			error = $_('auth.passwordTooShort');
			return;
		}

		isLoading = true;

		const { error: authError } = await supabase.auth.signUp({
			email,
			password
		});

		isLoading = false;

		if (authError) {
			error = authError.message;
		} else {
			success = true;
		}
	}
</script>

<svelte:head>
	<title>{$_('auth.signUpTitle')}</title>
</svelte:head>

<div class="flex items-center justify-center min-h-screen px-4">
	<div class="card w-full max-w-sm bg-base-200" style="box-shadow: 0 1px 3px rgba(0,0,0,0.06)">
		<div class="card-body">
			<h1 class="text-4xl font-semibold text-center tracking-tight text-primary">{$_('common.appName')}</h1>
			<p class="text-center text-base-content/70 text-sm mt-1">{$_('common.tagline')}</p>

			{#if success}
				<div class="alert alert-success mt-4" role="alert" aria-live="polite">
					<span>{$_('auth.checkEmail')}</span>
				</div>
				<p class="text-center mt-4">
					<a href="/login" class="link link-primary">{$_('auth.signIn')}</a>
				</p>
			{:else}
				<form onsubmit={handleRegister} class="space-y-4 mt-6">
					{#if error}
						<ErrorAlert message={error} />
					{/if}

					<div class="form-control">
						<label class="label" for="email">
							<span class="label-text">{$_('auth.emailLabel')}</span>
						</label>
						<input
							id="email"
							type="email"
							bind:value={email}
							class="input input-bordered w-full"
							placeholder={$_('auth.emailPlaceholder')}
							required
							aria-invalid={!!error}
						/>
					</div>

					<div class="form-control">
						<label class="label" for="password">
							<span class="label-text">{$_('auth.passwordLabel')}</span>
						</label>
						<input
							id="password"
							type="password"
							bind:value={password}
							class="input input-bordered w-full"
							placeholder={$_('auth.passwordHint')}
							required
							aria-invalid={!!error}
						/>
					</div>

					<div class="form-control">
						<label class="label" for="confirmPassword">
							<span class="label-text">{$_('auth.confirmPasswordLabel')}</span>
						</label>
						<input
							id="confirmPassword"
							type="password"
							bind:value={confirmPassword}
							class="input input-bordered w-full"
							placeholder={$_('auth.confirmPasswordPlaceholder')}
							required
							aria-invalid={!!error}
						/>
					</div>

					<button type="submit" class="btn btn-primary w-full" disabled={isLoading} aria-busy={isLoading}>
						{#if isLoading}
							<span class="loading loading-spinner loading-sm" aria-hidden="true"></span>
							<span class="sr-only">{$_('common.loading')}</span>
						{:else}
							{$_('auth.signUp')}
						{/if}
					</button>
				</form>

				<p class="text-center text-sm mt-4">
					{$_('auth.hasAccount')}
					<a href="/login" class="link link-primary">{$_('auth.logIn')}</a>
				</p>
			{/if}
		</div>
	</div>
</div>
