<script>
	import { _ } from 'svelte-i18n';

	let { event, isProcessing = false, onapprove, onreject } = $props();

	/** @param {any} event */
	function getChangeSet(event) {
		const sources = event.event_sources || [];
		for (const source of sources) {
			if (
				source?.change_set &&
				!source.is_undone &&
				(source.source_type === 'update' || source.source_type === 'cancellation')
			) {
				return source.change_set;
			}
		}
		for (const source of sources) {
			if (source?.change_set && !source.is_undone) return source.change_set;
		}
		return null;
	}

	/** @param {string} field */
	function fieldLabel(field) {
		/** @type {Record<string, string>} */
		const map = {
			title: $_('events.fieldTitle'),
			start_datetime: $_('events.fieldStart'),
			end_datetime: $_('events.fieldEnd'),
			location: $_('events.fieldLocation'),
			description: $_('events.fieldDescription'),
			status: $_('events.fieldStatus'),
			all_day: $_('events.fieldAllDay')
		};
		return map[field] || field;
	}

	/** @param {any} value */
	function formatValue(value) {
		if (value === null || value === undefined || value === '') return $_('events.none');
		if (typeof value === 'boolean') return value ? 'Yes' : 'No';
		if (typeof value === 'string' && value.includes('T')) {
			try {
				return new Date(value).toLocaleString(undefined, {
					month: 'short',
					day: 'numeric',
					hour: 'numeric',
					minute: '2-digit'
				});
			} catch {
				return String(value);
			}
		}
		return String(value);
	}

	let changeSet = $derived(getChangeSet(event));
	let changes = $derived(changeSet?.changes || []);
</script>

<div class="flex items-start justify-between p-4 border-b border-base-200">
	<div class="min-w-0 flex-1">
		<div class="flex items-center gap-2">
			<a href="/app/events/{event.id}" class="link link-hover">
				<h4 class="font-semibold text-base">{event.title}</h4>
			</a>
		</div>
		{#if changes.length > 0}
			<ul class="mt-2 space-y-1">
				{#each changes as change}
					<li class="text-sm text-base-content/80">
						<span class="font-medium">{fieldLabel(change.field)}</span>:
						<span class="line-through text-base-content/50">{formatValue(change.before)}</span>
						→
						<span>{formatValue(change.after)}</span>
					</li>
				{/each}
			</ul>
		{:else}
			<p class="text-sm text-base-content/60 mt-1">{$_('home.changesSectionDescription')}</p>
		{/if}
		<div class="flex items-center gap-2 mt-2">
			{#if isProcessing}
				<span class="loading loading-spinner loading-sm" aria-live="polite" aria-label={$_('common.loading')}></span>
			{:else}
				<button
					class="btn btn-sm btn-success"
					onclick={() => onapprove?.(event)}
					aria-label={$_('events.acceptChange')}
				>
					<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"
						><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg
					>
				</button>
				<a href="/app/events/{event.id}" class="btn btn-sm btn-primary" aria-label={$_('common.edit')}>
					<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"
						><path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"
						/></svg
					>
					{$_('common.edit')}
				</a>
				<button
					class="btn btn-sm btn-error"
					onclick={() => onreject?.(event)}
					aria-label={$_('events.rejectChange')}
				>
					<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"
						><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg
					>
				</button>
			{/if}
		</div>
	</div>
</div>
