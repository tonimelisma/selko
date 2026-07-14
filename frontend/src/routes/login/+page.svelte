<script>
	import { goto } from '$app/navigation';
	import { _ } from 'svelte-i18n';
	import { supabase } from '$lib/supabase.js';
	import ErrorAlert from '$lib/components/ErrorAlert.svelte';
	import LogoMark from '$lib/components/LogoMark.svelte';

	let email = $state('');
	let password = $state('');
	let error = $state('');
	let isLoading = $state(false);

	/** @param {SubmitEvent} event */
	async function handleLogin(event) {
		event.preventDefault();
		error = '';
		isLoading = true;

		const { error: authError } = await supabase.auth.signInWithPassword({
			email,
			password
		});

		if (authError) {
			error = authError.message;
			isLoading = false;
		} else {
			goto('/app');
		}
	}
</script>

<svelte:head>
	<title>{$_('auth.signInTitle')}</title>
</svelte:head>

<div class="flex min-h-screen items-center justify-center bg-base-100 px-4 py-10">
	<div class="warm-card w-full max-w-sm">
		<div class="card-body">
			<div class="flex flex-col items-center">
				<LogoMark size={48} />
				<h1 class="mt-4 text-3xl font-extrabold tracking-tight">{$_('common.appName')}</h1>
				<p class="mt-1 text-center text-sm text-base-content/60">{$_('common.tagline')}</p>
			</div>

			<form onsubmit={handleLogin} class="space-y-4 mt-6">
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
						class="input input-bordered w-full bg-base-100"
						placeholder={$_('auth.emailPlaceholder')}
						required
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
						class="input input-bordered w-full bg-base-100"
						placeholder={$_('auth.passwordPlaceholder')}
						required
					/>
				</div>

				<button type="submit" class="btn btn-primary w-full rounded-[14px] shadow-brand" disabled={isLoading} aria-busy={isLoading}>
					{#if isLoading}
						<span class="loading loading-spinner loading-sm" aria-hidden="true"></span>
						<span class="sr-only">{$_('common.loading')}</span>
					{:else}
						{$_('auth.signIn')}
					{/if}
				</button>
			</form>

			<p class="text-center text-sm mt-4">
				{$_('auth.noAccount')}
				<a href="/register" class="link link-primary">{$_('auth.signUp')}</a>
			</p>
		</div>
	</div>
</div>
