<script>
	let { tone = 'neutral', category = '', label = '', removeLabel = '', onremove } = $props();
</script>

<div class="flex min-h-11 items-center rounded-full border border-base-300 bg-base-200 pl-3">
	<span class="mr-2 h-2.5 w-2.5 rounded-full {tone === 'error' ? 'bg-error' : 'bg-success'}" aria-hidden="true"></span>
	<span class="mr-2 text-xs font-bold uppercase tracking-[0.08em] {tone === 'error' ? 'text-error' : 'semantic-status-success'}">{category}</span>
	<span class="text-sm font-semibold">{label}</span>
	<button type="button" class="btn btn-circle action-tertiary ml-1" aria-label={removeLabel} onclick={onremove}>
		<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg>
	</button>
</div>
