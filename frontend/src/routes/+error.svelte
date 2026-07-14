<script>
	import { page } from '$app/stores';
	import { _ } from 'svelte-i18n';
</script>

<div class="flex min-h-screen items-center justify-center bg-base-100 px-4">
	<div class="warm-card max-w-md p-8 text-center">
		<h1 class="mb-4 text-6xl font-extrabold text-primary/30">{$page.status}</h1>
		<h2 class="mb-2 text-2xl font-extrabold">
			{#if $page.status === 404}
				{$_('errors.pageNotFound')}
			{:else}
				{$_('errors.somethingWentWrong')}
			{/if}
		</h2>
		<p class="text-base-content/60 mb-6">
			{#if $page.error?.message}
				{$page.error.message}
			{:else if $page.status === 404}
				{$_('errors.pageNotFoundDescription')}
			{:else}
				{$_('errors.unexpectedError')}
			{/if}
		</p>
		<a href="/app" class="btn btn-primary rounded-[14px] shadow-brand">{$_('errors.backToApp')}</a>
	</div>
</div>
