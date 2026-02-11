<script>
	import { goto } from '$app/navigation';
	import { supabase } from '$lib/supabase.js';

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
	<title>Sign in - Selko</title>
</svelte:head>

<div class="flex items-center justify-center min-h-screen px-4">
	<div class="card w-full max-w-sm bg-base-200" style="box-shadow: 0 1px 3px rgba(0,0,0,0.06)">
		<div class="card-body">
			<h1 class="text-4xl font-semibold text-center tracking-tight text-primary">Selko</h1>
			<p class="text-center text-base-content/70 text-sm mt-1">Clear your mind.</p>

			<form onsubmit={handleLogin} class="space-y-4 mt-6">
				{#if error}
					<div class="alert alert-error" role="alert" aria-live="polite">
						<span>{error}</span>
					</div>
				{/if}

				<div class="form-control">
					<label class="label" for="email">
						<span class="label-text">Email</span>
					</label>
					<input
						id="email"
						type="email"
						bind:value={email}
						class="input input-bordered w-full"
						placeholder="you@example.com"
						required
					/>
				</div>

				<div class="form-control">
					<label class="label" for="password">
						<span class="label-text">Password</span>
					</label>
					<input
						id="password"
						type="password"
						bind:value={password}
						class="input input-bordered w-full"
						placeholder="Your password"
						required
					/>
				</div>

				<button type="submit" class="btn btn-primary w-full" disabled={isLoading} aria-busy={isLoading}>
					{#if isLoading}
						<span class="loading loading-spinner loading-sm" aria-hidden="true"></span>
						<span class="sr-only">Loading</span>
					{:else}
						Sign in
					{/if}
				</button>
			</form>

			<p class="text-center text-sm mt-4">
				Don't have an account?
				<a href="/register" class="link link-primary">Sign up</a>
			</p>
		</div>
	</div>
</div>
