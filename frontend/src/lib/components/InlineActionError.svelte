<script>
	import { _ } from 'svelte-i18n';

	let {
		message = '',
		onretry = undefined,
		onaction = undefined,
		actionLabel = '',
		ondismiss = undefined
	} = $props();
</script>

{#if message}
	<div
		class="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-error/25 bg-error/5 px-3 py-2 text-sm text-error"
		role="alert"
		aria-live="assertive"
	>
		<span class="min-w-0 flex-1">{message}</span>
		<div class="flex items-center gap-1">
			{#if onretry}
				<button class="btn btn-ghost btn-sm min-h-11" onclick={onretry}>{$_('common.retry')}</button>
			{/if}
			{#if onaction}
				<button class="btn btn-ghost btn-sm min-h-11" onclick={onaction}>{actionLabel}</button>
			{/if}
			{#if ondismiss}
				<button class="btn btn-ghost btn-sm min-h-11" onclick={ondismiss} aria-label={$_('common.dismiss')}>×</button>
			{/if}
		</div>
	</div>
{/if}
