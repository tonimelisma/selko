<script>
	import { page } from '$app/stores';
</script>

<div class="min-h-screen flex items-center justify-center bg-base-200">
	<div class="text-center p-8">
		<h1 class="text-6xl font-bold text-base-content/20 mb-4">{$page.status}</h1>
		<h2 class="text-2xl font-semibold mb-2">
			{#if $page.status === 404}
				Page Not Found
			{:else}
				Something Went Wrong
			{/if}
		</h2>
		<p class="text-base-content/60 mb-6">
			{#if $page.error?.message}
				{$page.error.message}
			{:else if $page.status === 404}
				The page you're looking for doesn't exist.
			{:else}
				An unexpected error occurred.
			{/if}
		</p>
		<a href="/app" class="btn btn-primary">Back to App</a>
	</div>
</div>
