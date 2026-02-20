<script>
	/** @type {{ message: string, onretry?: (() => void) | null, onaction?: (() => void) | null, actionLabel?: string }} */
	let { message, onretry = null, onaction = null, actionLabel = '' } = $props();
</script>

{#if message}
	<div class="alert alert-error mb-4" role="alert" aria-live="polite">
		<span>{message}</span>
		{#if onretry}
			<button class="btn btn-sm btn-ghost" onclick={onretry}>Retry</button>
		{/if}
		{#if onaction}
			<button class="btn btn-sm btn-ghost" onclick={onaction}>{actionLabel}</button>
		{/if}
	</div>
{/if}
