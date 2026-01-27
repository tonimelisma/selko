<script>
	import { supabase } from '$lib/supabase.js';

	let email = $state('');
	let password = $state('');
	let confirmPassword = $state('');
	let error = $state('');
	let success = $state(false);
	let isLoading = $state(false);

	async function handleRegister(event) {
		event.preventDefault();
		error = '';

		if (password !== confirmPassword) {
			error = 'Passwords do not match';
			return;
		}

		if (password.length < 6) {
			error = 'Password must be at least 6 characters';
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
	<title>Register - Selko</title>
</svelte:head>

<div class="flex items-center justify-center min-h-screen px-4">
	<div class="card w-full max-w-sm bg-base-200 shadow-xl">
		<div class="card-body">
			<h1 class="card-title text-2xl font-bold justify-center">Create Account</h1>

			{#if success}
				<div class="alert alert-success mt-4">
					<span>Registration successful! Check your email to confirm your account.</span>
				</div>
				<p class="text-center mt-4">
					<a href="/login" class="link link-primary">Go to Login</a>
				</p>
			{:else}
				<form onsubmit={handleRegister} class="space-y-4 mt-4">
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
							placeholder="At least 6 characters"
							required
						/>
					</div>

					<div class="form-control">
						<label class="label" for="confirmPassword">
							<span class="label-text">Confirm Password</span>
						</label>
						<input
							id="confirmPassword"
							type="password"
							bind:value={confirmPassword}
							class="input input-bordered w-full"
							placeholder="Confirm your password"
							required
						/>
					</div>

					<button type="submit" class="btn btn-primary w-full" disabled={isLoading}>
						{#if isLoading}
							<span class="loading loading-spinner loading-sm"></span>
						{:else}
							Register
						{/if}
					</button>
				</form>

				<div class="divider">OR</div>

				<p class="text-center text-sm">
					Already have an account?
					<a href="/login" class="link link-primary">Login</a>
				</p>
			{/if}
		</div>
	</div>
</div>
