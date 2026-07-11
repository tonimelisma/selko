<script>
	import { onMount } from 'svelte';
	import { _ } from 'svelte-i18n';
	import { fetchActivityEvents } from '$lib/services/events.js';
	import { syncEventToCalendar, undoHistoryEvent } from '$lib/api/backend.js';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import ErrorAlert from '$lib/components/ErrorAlert.svelte';

	/** @type {any[]} */
	let events = $state([]);
	let totalCount = $state(0);
	let isLoading = $state(true);
	let isLoadingMore = $state(false);
	let error = $state('');
	let offset = $state(0);
	const limit = 20;

	let hasMore = $derived(events.length < totalCount);

	let groupedByDate = $derived(() => {
		const groups = new Map();
		const today = new Date();
		today.setHours(0, 0, 0, 0);
		const yesterday = new Date(today);
		yesterday.setDate(yesterday.getDate() - 1);

		for (const event of events) {
			const eventDate = new Date(event.updated_at);
			eventDate.setHours(0, 0, 0, 0);

			let dateLabel;
			if (eventDate.getTime() === today.getTime()) {
				dateLabel = $_('history.today');
			} else if (eventDate.getTime() === yesterday.getTime()) {
				dateLabel = $_('history.yesterday');
			} else {
				dateLabel = eventDate.toLocaleDateString(undefined, {
					weekday: 'long',
					month: 'long',
					day: 'numeric',
					year: 'numeric'
				});
			}

			if (!groups.has(dateLabel)) {
				groups.set(dateLabel, []);
			}
			groups.get(dateLabel).push(event);
		}
		return groups;
	});

	onMount(async () => {
		await loadEvents();
	});

	async function loadEvents() {
		isLoading = true;
		error = '';
		const result = await fetchActivityEvents({ limit, offset: 0 });
		if (result.error) {
			error = result.error.message;
		} else {
			events = result.data;
			totalCount = result.count || 0;
			offset = result.data.length;
		}
		isLoading = false;
	}

	async function loadMore() {
		isLoadingMore = true;
		const result = await fetchActivityEvents({ limit, offset });
		if (result.error) {
			error = result.error.message;
		} else {
			events = [...events, ...result.data];
			offset += result.data.length;
		}
		isLoadingMore = false;
	}

	/** @param {any} event */
	function isChangeEvent(event) {
		const sources = event.event_sources || [];
		return sources.some(
			(s) =>
				!s.is_undone &&
				(s.source_type === 'update' || s.source_type === 'cancellation') &&
				s.change_set
		);
	}

	/** @param {any} event */
	function getChangeSet(event) {
		const sources = event.event_sources || [];
		for (const source of sources) {
			if (
				!source.is_undone &&
				(source.source_type === 'update' || source.source_type === 'cancellation') &&
				source.change_set
			) {
				return source.change_set;
			}
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

	/** @param {any} event */
	function getChangeSummary(event) {
		const changeSet = getChangeSet(event);
		if (!changeSet?.changes?.length) return '';
		return changeSet.changes
			.map(
				(/** @type {any} */ c) =>
					`${fieldLabel(c.field)}: ${formatValue(c.before)} → ${formatValue(c.after)}`
			)
			.join('; ');
	}

	/** @param {any} event */
	function getActionDescription(event) {
		if (isChangeEvent(event)) {
			return $_('history.actionChangeApplied');
		}
		/** @type {Record<string, string>} */
		const statusMap = {
			approved: $_('history.statusApproved'),
			synced: $_('history.statusSynced'),
			sync_failed: $_('history.statusSyncFailed'),
			rejected: $_('history.statusRejected'),
			cancelled: $_('history.statusCancelled')
		};
		if (event.status === 'synced' || event.status === 'approved') {
			return $_('history.actionNewEvent');
		}
		return statusMap[event.status] || event.status;
	}

	/** @param {any} event */
	function getActionTime(event) {
		try {
			return new Date(event.updated_at).toLocaleTimeString(undefined, {
				hour: 'numeric',
				minute: '2-digit'
			});
		} catch {
			return '';
		}
	}

	/** @param {any} event */
	function getSourceInfo(event) {
		const sources = event.event_sources || [];
		const firstSource = sources[0];

		if (firstSource?.source_origin === 'google_photos') {
			return $_('history.fromPhoto');
		}

		const email = firstSource?.emails;
		if (email) {
			const name = email.from_name || email.from_email || $_('history.unknownSender');
			return $_('history.from', { values: { name } });
		}
		return '';
	}

	/** @param {any} event */
	async function handleUndo(event) {
		const { error: undoError } = await undoHistoryEvent(event.id);
		if (undoError) {
			error = undoError.message;
			return;
		}
		events = events.filter((e) => e.id !== event.id);
		totalCount--;
	}

	/** @param {any} event */
	async function handleRetry(event) {
		const result = await syncEventToCalendar(event.id);
		if (result.error) {
			error = result.error.message;
			return;
		}
		events = events.map((e) => (e.id === event.id ? { ...e, status: 'synced' } : e));
	}
</script>

<PageHeader title={$_('history.title')} />

{#if isLoading}
	<div class="space-y-4">
		<div class="h-6 bg-base-200 rounded animate-pulse w-24"></div>
		<div class="h-16 bg-base-200 rounded animate-pulse"></div>
		<div class="h-16 bg-base-200 rounded animate-pulse"></div>
		<div class="h-16 bg-base-200 rounded animate-pulse"></div>
	</div>
{:else if error}
	<ErrorAlert message={error} onretry={loadEvents} />
{:else if events.length === 0}
	<EmptyState
		heading={$_('history.noActivity')}
		description={$_('history.noActivityDescription')}
	/>
{:else}
	<div class="space-y-6">
		{#each [...groupedByDate().entries()] as [dateLabel, dateEvents]}
			<div>
				<h2 class="text-sm font-semibold text-base-content/60 mb-3">{dateLabel}</h2>
				<div>
					{#each dateEvents as event (event.id)}
						<div class="flex items-start justify-between p-3 border-b border-base-200">
							<div class="min-w-0 flex-1">
								<div class="flex items-center gap-2 flex-wrap">
									<span class="font-medium text-sm">{event.title}</span>
									<StatusBadge status={event.status} />
									{#if isChangeEvent(event)}
										<span class="badge badge-sm badge-outline">{$_('home.changesSection')}</span>
									{:else}
										<span class="badge badge-sm badge-outline">{$_('home.newSection')}</span>
									{/if}
								</div>
								<div class="flex items-center gap-2 mt-1 text-xs text-base-content/60 flex-wrap">
									<span>{getActionTime(event)}</span>
									<span>{getActionDescription(event)}</span>
									{#if getSourceInfo(event)}
										<span>- {getSourceInfo(event)}</span>
									{/if}
								</div>
								{#if isChangeEvent(event) && getChangeSummary(event)}
									<p class="text-xs text-base-content/70 mt-1">
										{$_('history.changeSummary', { values: { summary: getChangeSummary(event) } })}
									</p>
								{/if}
							</div>
							<div class="flex items-center gap-1 flex-shrink-0 ml-2">
								{#if event.status === 'sync_failed'}
									<button
										class="btn btn-outline btn-warning btn-xs"
										onclick={() => handleRetry(event)}
									>
										{$_('history.retrySync')}
									</button>
								{/if}
								{#if ['approved', 'synced', 'rejected', 'cancelled'].includes(event.status)}
									<button class="btn btn-outline btn-xs" onclick={() => handleUndo(event)}>
										{$_('history.undo')}
									</button>
								{/if}
							</div>
						</div>
					{/each}
				</div>
			</div>
		{/each}

		{#if hasMore}
			<div class="text-center py-4">
				<button class="btn btn-ghost" onclick={loadMore} disabled={isLoadingMore}>
					{#if isLoadingMore}
						<span class="loading loading-spinner loading-sm"></span>
					{:else}
						{$_('history.loadMore')}
					{/if}
				</button>
			</div>
		{/if}
	</div>
{/if}
