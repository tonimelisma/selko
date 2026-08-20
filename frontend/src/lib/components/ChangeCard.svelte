<script>
	import { _ } from 'svelte-i18n';
	import { formatChangeValue } from '$lib/format-change-value.js';
	import StateTag from './StateTag.svelte';
	import InlineActionError from './InlineActionError.svelte';

	let { event, proposal = null, error = '', isProcessing = false, canApprove = true, onapprove, onreject } = $props();

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

	let activeProposal = $derived(proposal?.status === 'pending' ? proposal : null);
	let changes = $derived(activeProposal?.change_set?.changes || []);
	let proposalAvailable = $derived(Boolean(activeProposal && (changes.length > 0 || activeProposal.kind === 'cancellation')));
	let dateParts = $derived(() => {
		if (!event.start_datetime) return { month: '', day: '' };
		const date = new Date(event.start_datetime);
		return {
			month: date.toLocaleDateString(undefined, { month: 'short' }).toUpperCase(),
			day: date.toLocaleDateString(undefined, { day: 'numeric' })
		};
	});
</script>

<div class="warm-card border-b border-base-300 p-4">
	<div class="flex gap-3 sm:gap-4">
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
			<StateTag kind="changed" label={$_('home.changesSection')} />
		</div>
		{#if changes.length > 0}
			<ul class="mt-2 space-y-1">
				{#each changes as change}
					<li class="text-[13px] text-base-content/75"><span class="font-semibold">{fieldLabel(change.field)}</span>: <span class="text-base-content/45 line-through">{formatValue(change.before)}</span> <span class="px-1 text-accent" aria-hidden="true">→</span> <span class="font-semibold">{formatValue(change.after)}</span></li>
				{/each}
			</ul>
		{:else}
			<div class="alert alert-error mt-2 py-2 text-[13px]" role="alert">
				<span>{$_('review.changeProposalUnavailable')}</span>
			</div>
		{/if}
		<InlineActionError message={error} />
	</div>
	</div>
		<div class="peer-action-wrap mt-3">
			<div class="peer-action-group" data-peer-count="3">
				<button
					class="btn peer-action peer-action-accept"
					disabled={isProcessing || !canApprove || !proposalAvailable}
					onclick={() => onapprove?.(event)}
					aria-label={`${$_('events.accept')} ${event.title}${canApprove ? '' : `. ${$_('integrations.calendarRequiredToAccept')}`}`}
					aria-busy={isProcessing}
				>
					{#if isProcessing}<span class="loading loading-spinner loading-xs" aria-hidden="true"></span>{:else}<svg xmlns="http://www.w3.org/2000/svg" class="peer-icon h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.3" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="m5 12 4 4L19 6" /></svg>{/if}
					<span>{$_('events.accept')}</span>
				</button>
				<a href="/app/events/{event.id}" class="btn peer-action peer-action-secondary" class:btn-disabled={isProcessing} aria-disabled={isProcessing} aria-label={`${$_('common.edit')} ${event.title}`}>
					<span>{$_('common.edit')}</span>
					<svg xmlns="http://www.w3.org/2000/svg" class="peer-icon h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.3" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M21.17 6.81a1 1 0 0 0-3.98-3.99L3.84 16.17a2 2 0 0 0-.5.83l-1.32 4.35a.5.5 0 0 0 .62.63l4.35-1.32a2 2 0 0 0 .83-.5z"/><path d="m15 5 4 4"/></svg>
				</a>
				<button class="btn peer-action peer-action-destructive" disabled={isProcessing || !proposalAvailable} onclick={() => onreject?.(event)} aria-label={`${$_('events.reject')} ${event.title}`} aria-busy={isProcessing}>
					{#if isProcessing}<span class="loading loading-spinner loading-xs" aria-hidden="true"></span>{:else}<svg xmlns="http://www.w3.org/2000/svg" class="peer-icon h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.3" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="m7 7 10 10M17 7 7 17" /></svg>{/if}
					<span>{$_('events.reject')}</span>
				</button>
			</div>
		</div>
</div>
