<script>
	import { tick } from 'svelte';
	import { _ } from 'svelte-i18n';
	import { formatEventDateTime } from '$lib/format-event-datetime.js';
	import StateTag from './StateTag.svelte';
	import InlineActionError from './InlineActionError.svelte';

	let { event, error = '', isProcessing = false, canApprove = true, onapprove, onreject } = $props();

	let sourceOrigin = $derived(() => {
		const sources = event.event_sources || [];
		return sources[0]?.source_origin || 'email';
	});

	let formattedDateTime = $derived(() => formatEventDateTime(event, $_));
	let dateParts = $derived(() => {
		if (!event.start_datetime) return { month: '', day: '' };
		const date = new Date(event.start_datetime);
		return {
			month: date.toLocaleDateString(undefined, { month: 'short' }).toUpperCase(),
			day: date.toLocaleDateString(undefined, { day: 'numeric' })
		};
	});

	/** @type {boolean} */
	let descriptionExpanded = $state(false);
	/** @type {boolean} */
	let descriptionOverflows = $state(false);
	/** @type {HTMLElement | undefined} */
	let descriptionEl = $state();

	function remeasureDescription() {
		if (!descriptionEl || descriptionExpanded) return;
		descriptionOverflows = descriptionEl.scrollHeight > descriptionEl.clientHeight;
	}

	/**
	 * Measure whether the clamped description overflows; re-check on resize.
	 * @param {HTMLElement} node
	 */
	function descriptionOverflow(node) {
		descriptionEl = node;
		remeasureDescription();
		/** @type {ResizeObserver | undefined} */
		let ro;
		if (typeof ResizeObserver !== 'undefined') {
			ro = new ResizeObserver(() => remeasureDescription());
			ro.observe(node);
		}
		return {
			destroy() {
				ro?.disconnect();
				if (descriptionEl === node) descriptionEl = undefined;
			}
		};
	}

	$effect(() => {
		void event.id;
		void event.description;
		descriptionExpanded = false;
		descriptionOverflows = false;
		queueMicrotask(() => remeasureDescription());
	});

	/**
	 * Native click listener so stopPropagation runs before ancestors see the bubble
	 * (Svelte 5 delegates onclick to the root, which is too late).
	 * @param {HTMLButtonElement} node
	 */
	function descriptionToggle(node) {
		/** @param {MouseEvent} e */
		async function onClick(e) {
			e.stopPropagation();
			descriptionExpanded = !descriptionExpanded;
			if (!descriptionExpanded) {
				await tick();
				remeasureDescription();
			}
		}
		node.addEventListener('click', onClick);
		return {
			destroy() {
				node.removeEventListener('click', onClick);
			}
		};
	}
</script>

<div class="warm-card border-b border-base-300 p-4">
	<div class="flex gap-3 sm:gap-4">
		<div class="date-chip flex h-[52px] w-[50px] shrink-0 flex-col items-center justify-center">
			{#if dateParts().month}
				<span class="text-[10px] font-bold tracking-[0.12em] text-primary">{dateParts().month}</span>
				<span class="text-xl font-extrabold leading-5">{dateParts().day}</span>
			{:else}
				<span class="text-xs font-bold text-primary">—</span>
			{/if}
		</div>

		<div class="min-w-0 flex-1">
		<div class="flex flex-wrap items-center gap-2">
			{#if sourceOrigin() === 'google_photos'}
				<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 shrink-0 text-base-content/50" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-label={$_('eventSource.photoSource')}>
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
				</svg>
			{:else}
				<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 shrink-0 text-base-content/50" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-label={$_('eventSource.emailSource')}>
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5v10a2 2 0 002 2z" />
				</svg>
			{/if}
			<a href="/app/events/{event.id}" class="min-w-0 link link-hover">
				<h4 class="truncate text-[15px] font-bold">{event.title}</h4>
			</a>
			{#if event.importance === 'fyi'}
				<span class="badge badge-neutral-warm badge-sm">{$_('events.fyi')}</span>
			{:else}
				<StateTag kind="new" label={$_('home.newSection')} />
			{/if}
		</div>
		<p class="mt-1 text-[12px] font-medium text-base-content/55">{formattedDateTime()}</p>
		{#if event.location}
			<p class="mt-0.5 text-[13px] text-base-content/70">{event.location}</p>
		{/if}
		{#if event.description}
			<div class="mt-1">
				<p
					class="break-words whitespace-pre-wrap text-[13px] text-base-content/60"
					class:line-clamp-3={!descriptionExpanded}
					use:descriptionOverflow
				>
					{event.description}
				</p>
				{#if descriptionOverflows || descriptionExpanded}
					<button
						type="button"
						class="link link-primary mt-0.5 inline-flex min-h-11 items-center text-xs font-semibold"
						aria-expanded={descriptionExpanded}
						use:descriptionToggle
					>
						{descriptionExpanded ? $_('events.showLess') : $_('events.showMore')}
					</button>
				{/if}
			</div>
		{/if}
		<InlineActionError message={error} />
	</div>
	</div>
		<div class="peer-action-wrap mt-3">
			<div class="peer-action-group" data-peer-count="3">
				<button
					class="btn peer-action peer-action-accept"
					disabled={isProcessing || !canApprove}
					onclick={() => onapprove?.(event)}
					aria-label={`${$_('events.accept')} ${event.title}${canApprove ? '' : `. ${$_('integrations.calendarRequiredToAccept')}`}`}
					aria-busy={isProcessing}
				>
					{#if isProcessing}<span class="loading loading-spinner loading-xs" aria-hidden="true"></span>{:else}<svg xmlns="http://www.w3.org/2000/svg" class="peer-icon h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.3" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="m5 12 4 4L19 6" /></svg>{/if}
					<span>{$_('events.accept')}</span>
				</button>
				<a
					href="/app/events/{event.id}"
					class="btn peer-action peer-action-secondary"
					class:btn-disabled={isProcessing}
					aria-disabled={isProcessing}
					aria-label={`${$_('common.edit')} ${event.title}`}
				>
					<span>{$_('common.edit')}</span>
					<svg xmlns="http://www.w3.org/2000/svg" class="peer-icon h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.3"><path stroke-linecap="round" stroke-linejoin="round" d="M21.17 6.81a1 1 0 0 0-3.98-3.99L3.84 16.17a2 2 0 0 0-.5.83l-1.32 4.35a.5.5 0 0 0 .62.63l4.35-1.32a2 2 0 0 0 .83-.5z"/><path d="m15 5 4 4"/></svg>
				</a>
				<button class="btn peer-action peer-action-destructive" disabled={isProcessing} onclick={() => onreject?.(event)} aria-label={`${$_('events.reject')} ${event.title}`} aria-busy={isProcessing}>
					{#if isProcessing}<span class="loading loading-spinner loading-xs" aria-hidden="true"></span>{:else}<svg xmlns="http://www.w3.org/2000/svg" class="peer-icon h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.3" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="m7 7 10 10M17 7 7 17" /></svg>{/if}
					<span>{$_('events.reject')}</span>
				</button>
			</div>
		</div>
</div>
