<script>
	import { _ } from 'svelte-i18n';
	import { formatChangeValue } from '$lib/format-change-value.js';

	let { event, isProcessing = false, onapprove, onreject } = $props();

	/** @param {any} item */
	function getChangeSet(item) {
		const sources = item.event_sources || [];
		return sources.find(
			/** @param {any} source */
			(source) => source?.change_set && !source.is_undone && (source.source_type === 'update' || source.source_type === 'cancellation')
		)?.change_set || sources.find(
			/** @param {any} source */
			(source) => source?.change_set && !source.is_undone
		)?.change_set || null;
	}

	/** @param {string} field */
	function fieldLabel(field) {
		/** @type {Record<string, string>} */
		const map = { title: $_('events.fieldTitle'), start_datetime: $_('events.fieldStart'), end_datetime: $_('events.fieldEnd'), location: $_('events.fieldLocation'), description: $_('events.fieldDescription'), status: $_('events.fieldStatus'), all_day: $_('events.fieldAllDay') };
		return map[field] || field;
	}

	/** @param {any} value */
	function formatValue(value) {
		return formatChangeValue(value, $_('events.none'));
	}

	let changes = $derived(getChangeSet(event)?.changes || []);
	let dateParts = $derived(() => {
		if (!event.start_datetime) return { month: '', day: '' };
		const date = new Date(event.start_datetime);
		return {
			month: date.toLocaleDateString(undefined, { month: 'short' }).toUpperCase(),
			day: date.toLocaleDateString(undefined, { day: 'numeric' })
		};
	});
</script>

<div class="warm-card-row flex gap-3 border-b border-base-300 p-4 sm:gap-4">
	<div class="date-chip flex h-[52px] w-[50px] shrink-0 flex-col items-center justify-center">
		{#if dateParts().month}
			<span class="text-[10px] font-bold tracking-[0.12em] text-accent">{dateParts().month}</span>
			<span class="text-xl font-extrabold leading-5">{dateParts().day}</span>
		{:else}
			<span class="text-xs font-bold text-accent">—</span>
		{/if}
	</div>
	<div class="min-w-0 flex-1">
		<div class="flex flex-wrap items-center gap-2">
			<a href="/app/events/{event.id}" class="link link-hover"><h4 class="text-[15px] font-bold">{event.title}</h4></a>
			<span class="badge badge-changed badge-sm">{$_('home.changesSection')}</span>
		</div>
		{#if changes.length > 0}
			<ul class="mt-2 space-y-1">
				{#each changes as change}
					<li class="text-[13px] text-base-content/75"><span class="font-semibold">{fieldLabel(change.field)}</span>: <span class="text-base-content/45 line-through">{formatValue(change.before)}</span> <span class="px-1 text-accent">→</span> <span class="font-semibold">{formatValue(change.after)}</span></li>
				{/each}
			</ul>
		{:else}
			<p class="mt-1 text-[13px] text-base-content/60">{$_('home.changesSectionDescription')}</p>
		{/if}
		<div class="mt-3 flex items-center gap-2">
			<button class="btn btn-success btn-sm min-h-9 flex-1 rounded-[11px] text-[13px] font-bold" disabled={isProcessing} onclick={() => onapprove?.(event)} aria-label={$_('events.acceptChange')} aria-busy={isProcessing}>
				{#if isProcessing}<span class="loading loading-spinner loading-xs"></span>{:else}<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="m5 12 4 4L19 6" /></svg>{/if}
				<span>{$_('events.accept')}</span>
			</button>
			<a href="/app/events/{event.id}" class="btn btn-square btn-sm min-h-9 w-9 rounded-[11px] bg-base-200 text-base-content" class:btn-disabled={isProcessing} aria-label={$_('common.edit')}><svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8"><path stroke-linecap="round" stroke-linejoin="round" d="m15 5 4 4M4 20l4.5-1 10-10a2.1 2.1 0 0 0-3-3l-10 10L4 20z" /></svg></a>
			<button class="btn btn-square btn-sm min-h-9 w-9 rounded-[11px] bg-base-200 text-error" disabled={isProcessing} onclick={() => onreject?.(event)} aria-label={$_('events.rejectChange')} aria-busy={isProcessing}>{#if isProcessing}<span class="loading loading-spinner loading-xs"></span>{:else}<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8"><path stroke-linecap="round" d="m7 7 10 10M17 7 7 17" /></svg>{/if}</button>
		</div>
	</div>
</div>
