<script>
	import { _ } from 'svelte-i18n';
	import { formatChangeValue } from '$lib/format-change-value.js';

	let { open = false, event = null, conflict = null, isProcessing = false, onconfirm, oncancel } = $props();

	/** @type {HTMLDialogElement | null} */
	let dialogEl = $state(null);

	$effect(() => {
		if (!dialogEl) return;
		if (open && !dialogEl.open) dialogEl.showModal?.();
		if (!open && dialogEl.open) dialogEl.close?.();
	});

	/** @param {string} field */
	function fieldLabel(field) {
		/** @type {Record<string, string>} */
		const labels = {
			summary: $_('events.fieldTitle'),
			title: $_('events.fieldTitle'),
			start: $_('events.fieldStart'),
			end: $_('events.fieldEnd'),
			location: $_('events.fieldLocation'),
			description: $_('events.fieldDescription')
		};
		return labels[field] || field;
	}

	/** @param {unknown} value */
	function displayValue(value) {
		if (value && typeof value === 'object') {
			const bound = /** @type {{ date?: string, dateTime?: string, timeZone?: string }} */ (value);
			if (bound.date) return bound.date;
			if (bound.dateTime) {
				return `${bound.dateTime.replace('T', ' ')}${bound.timeZone ? ` (${bound.timeZone})` : ''}`;
			}
			return JSON.stringify(value);
		}
		return formatChangeValue(value, $_('events.none'));
	}
</script>

<dialog
	bind:this={dialogEl}
	class="modal"
	onclose={oncancel}
	aria-labelledby="undo-conflict-title"
	aria-describedby="undo-conflict-description"
>
	<div class="modal-box warm-card max-w-2xl">
		<h3 id="undo-conflict-title" class="text-lg font-extrabold">{$_('history.undoConflictTitle')}</h3>
		<p id="undo-conflict-description" class="pt-2 text-sm text-base-content/70">
			{$_('history.undoConflictDescription', { values: { title: event?.title || '' } })}
		</p>

		<div class="mt-4 space-y-3">
			{#each conflict?.differences || [] as difference}
				<section class="rounded-xl border border-base-300 p-3" aria-label={fieldLabel(difference.field)}>
					<h4 class="text-sm font-bold">{fieldLabel(difference.field)}</h4>
					<dl class="mt-2 grid gap-2 text-sm sm:grid-cols-2">
						<div>
							<dt class="text-xs font-bold uppercase tracking-wide text-base-content/60">{$_('history.selkoValue')}</dt>
							<dd class="mt-1 break-words">{displayValue(difference.selko)}</dd>
						</div>
						<div>
							<dt class="text-xs font-bold uppercase tracking-wide text-base-content/60">{$_('history.googleValue')}</dt>
							<dd class="mt-1 break-words">{displayValue(difference.google)}</dd>
						</div>
					</dl>
				</section>
			{/each}
		</div>

		<div class="modal-action peer-action-wrap">
			<div class="peer-action-group peer-action-group--trailing" data-peer-count="3">
				<button class="btn peer-action peer-action-secondary" onclick={oncancel} disabled={isProcessing}>{$_('common.cancel')}</button>
				{#if conflict?.google_event_url}
					<a class="btn peer-action peer-action-secondary" href={conflict.google_event_url} target="_blank" rel="noreferrer">
						{$_('history.openInGoogleCalendar')}
					</a>
				{/if}
				<button class="btn peer-action peer-action-destructive" onclick={onconfirm} disabled={isProcessing}>
					{#if isProcessing}<span class="loading loading-spinner loading-sm" aria-hidden="true"></span>{/if}
					{$_('history.forceUndo')}
				</button>
			</div>
		</div>
	</div>
	<form method="dialog" class="modal-backdrop">
		<button disabled={isProcessing}>{$_('common.close')}</button>
	</form>
</dialog>
