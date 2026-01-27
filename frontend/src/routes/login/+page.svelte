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
	<title>Login - Selko</title>
</svelte:head>

<div class="flex items-center justify-center min-h-screen px-4">
	<div class="card w-full max-w-sm bg-base-200 shadow-xl">
		<div class="card-body">
			<h1 class="card-title text-2xl font-bold justify-center">Login to Selko</h1>

			<form onsubmit={handleLogin} class="space-y-4 mt-4">
				{#if error}
					<div class="alert alert-error">
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

				<button type="submit" class="btn btn-primary w-full" disabled={isLoading}>
					{#if isLoading}
						<span class="loading loading-spinner loading-sm"></span>
					{:else}
						Login
					{/if}
				</button>
			</form>

			<div class="divider">OR</div>

			<p class="text-center text-sm">
				Don't have an account?
				<a href="/register" class="link link-primary">Register</a>
			</p>
		</div>
	</div>
</div>
