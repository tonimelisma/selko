<script>
	import { _ } from 'svelte-i18n';
	let { checked = false, disabled = false, onchange } = $props();
</script>

<div class="flex items-center gap-2">
	<span class="min-w-[64px] text-right text-sm font-semibold text-base-content/75">
		{checked ? $_('settings.included') : $_('settings.excluded')}
	</span>
	<button
		type="button"
		role="switch"
		aria-checked={checked}
		aria-label={checked ? $_('settings.excludeFolder') : $_('settings.includeFolder')}
		class="grid h-11 w-11 place-items-center rounded-[14px]"
		class:opacity-50={disabled}
		{disabled}
		onclick={() => onchange?.(!checked)}
	>
		<span class="relative block h-[26px] w-11 rounded-full transition-colors {checked ? 'bg-primary' : 'bg-base-300'}">
			<span class="absolute top-[3px] grid h-5 w-5 place-items-center rounded-full bg-surface text-[11px] font-bold text-ink shadow-sm transition-transform {checked ? 'translate-x-[21px]' : 'translate-x-[3px]'}">
				{checked ? '✓' : ''}
			</span>
		</span>
	</button>
</div>
