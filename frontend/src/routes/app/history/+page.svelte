<script>
	import { onDestroy, onMount } from 'svelte';
	import { _ } from 'svelte-i18n';
	import { fetchActivityEvents } from '$lib/services/events.js';
	import {
		fetchEmailHistory,
		fetchEmailProcessingState,
		queueEmailReprocess
	} from '$lib/services/email-history.js';
	import { syncEventToCalendar, undoHistoryEvent } from '$lib/api/backend.js';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import ErrorAlert from '$lib/components/ErrorAlert.svelte';
	import { resolveEventSender } from '$lib/event-sender.js';
	import { formatChangeValue } from '$lib/format-change-value.js';

	/** @type {any[]} */
	let events = $state([]);
	let totalCount = $state(0);
	/** @type {any[]} */
	let emailHistory = $state([]);
	let emailHistoryCount = $state(0);
	let isLoading = $state(true);
	let isLoadingMore = $state(false);
	/** Load/fetch errors that replace the list */
	let loadError = $state('');
	/** Per-action errors shown as a banner above the list */
	let actionError = $state('');
	let emailLoadError = $state('');
	let emailLoadingMore = $state(false);
	let emailOffset = $state(0);
	/** @type {Set<string>} */
	let emailTimedOut = $state(new Set());
	/** @type {any | null} Event that can be force-undone after CALENDAR_DIVERGED */
	let forceUndoEvent = $state(null);
	/** @type {Set<string>} */
	let processingEvents = $state(new Set());
	/** @type {Set<string>} */
	let processingEmails = $state(new Set());
	let offset = $state(0);
	const limit = 20;
	const emailPollIntervalMs = 750;
	const emailPollMaxAttempts = 40;
	/** @type {Map<string, ReturnType<typeof setTimeout>>} */
	const emailPollingTimers = new Map();
	/** @type {Set<string>} */
	const emailPolling = new Set();

	let hasMore = $derived(events.length < totalCount);
	let emailHasMore = $derived(emailHistory.length < emailHistoryCount);

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
		await Promise.all([loadEvents(), loadEmailHistory()]);
	});

	onDestroy(() => {
		for (const timer of emailPollingTimers.values()) clearTimeout(timer);
		emailPollingTimers.clear();
		emailPolling.clear();
	});

	async function loadEvents() {
		isLoading = true;
		loadError = '';
		actionError = '';
		const result = await fetchActivityEvents({ limit, offset: 0 });
		if (result.error) {
			loadError = result.error.message;
		} else {
			events = result.data;
			totalCount = result.count || 0;
			offset = result.data.length;
		}
		isLoading = false;
	}

	async function loadMore() {
		isLoadingMore = true;
		actionError = '';
		const result = await fetchActivityEvents({ limit, offset });
		if (result.error) {
			actionError = result.error.message;
		} else {
			events = [...events, ...result.data];
			offset += result.data.length;
		}
		isLoadingMore = false;
	}

	/** @param {number} [requestedLimit] */
	async function loadEmailHistory(requestedLimit = 20) {
		emailLoadError = '';
		const result = await fetchEmailHistory({ limit: requestedLimit, offset: 0 });
		if (result.error) {
			emailLoadError = result.error.message;
		} else {
			emailHistory = result.data;
			emailHistoryCount = result.count || 0;
			emailOffset = result.data.length;
		}
	}

	async function loadMoreEmailHistory() {
		if (emailLoadingMore || !emailHasMore) return;
		emailLoadingMore = true;
		emailLoadError = '';
		const result = await fetchEmailHistory({ limit: 20, offset: emailOffset });
		if (result.error) {
			emailLoadError = result.error.message;
		} else {
			const knownIds = new Set(emailHistory.map((email) => email.id));
			const additions = result.data.filter((email) => !knownIds.has(email.id));
			emailHistory = [...emailHistory, ...additions];
			emailOffset += result.data.length;
			if (typeof result.count === 'number') emailHistoryCount = result.count;
		}
		emailLoadingMore = false;
	}

	/** @param {any} email */
	function emailSender(email) {
		return email.from_name || email.from_email || $_('history.unknownSender');
	}

	/** @param {any} email */
	function emailOutcome(email) {
		if (email.processing_status === 'failed') return $_('history.emailFailed');
		/** @type {Record<string, string>} */
		const outcomes = {
			no_event: $_('history.emailNoEvent'),
			event_created: $_('history.emailEventCreated'),
			event_updated: $_('history.emailEventUpdated'),
			event_created_and_updated: $_('history.emailEventCreatedAndUpdated'),
			event_cancelled: $_('history.emailEventCancelled'),
			event_matched: $_('history.emailEventMatched'),
			calendar_invite: $_('history.emailCalendarInvite')
		};
		return outcomes[email.processing_outcome] || $_('history.emailProcessed');
	}

	/** @param {any} email */
	function emailTime(email) {
		try {
			return new Date(email.date_sent || email.processed_at).toLocaleString(undefined, {
				dateStyle: 'medium',
				timeStyle: 'short'
			});
		} catch {
			return '';
		}
	}

	/** @param {string} emailId */
	function startEmailProcessing(emailId) {
		processingEmails = new Set([...processingEmails, emailId]);
		emailTimedOut = new Set([...emailTimedOut].filter((id) => id !== emailId));
		actionError = '';
	}

	/** @param {string} emailId */
	function stopEmailProcessing(emailId) {
		const next = new Set(processingEmails);
		next.delete(emailId);
		processingEmails = next;
	}

	/** @param {string} emailId */
	function stopEmailPolling(emailId) {
		const timer = emailPollingTimers.get(emailId);
		if (timer) clearTimeout(timer);
		emailPollingTimers.delete(emailId);
		emailPolling.delete(emailId);
	}

	/** @param {string} emailId @param {any} state */
	function applyEmailProcessingState(emailId, state) {
		emailHistory = emailHistory.map((item) =>
			item.id === emailId ? { ...item, ...state } : item
		);
	}

	/** @param {string} emailId */
	function pollEmailUntilTerminal(emailId) {
		stopEmailPolling(emailId);
		emailPolling.add(emailId);
		let attempts = 0;

		const poll = async () => {
			if (!emailPolling.has(emailId)) return;
			const result = await fetchEmailProcessingState(emailId);
			if (!emailPolling.has(emailId)) return;
			if (result.error) {
				actionError = result.error.message;
				emailTimedOut = new Set([...emailTimedOut, emailId]);
				stopEmailPolling(emailId);
				stopEmailProcessing(emailId);
				return;
			}
			const state = result.data;
			if (state) applyEmailProcessingState(emailId, state);
			if (state && ['processed', 'failed'].includes(state.processing_status)) {
				stopEmailPolling(emailId);
				stopEmailProcessing(emailId);
				// Reprocessing temporarily removes the row from the server-side
				// processed/failed result set. Refresh the complete loaded window so
				// offset pagination cannot skip the row that shifted across a page.
				await loadEmailHistory(Math.max(emailOffset, 20));
				return;
			}
			attempts += 1;
			if (attempts >= emailPollMaxAttempts) {
				actionError = $_('history.emailReprocessTimeout');
				emailTimedOut = new Set([...emailTimedOut, emailId]);
				stopEmailPolling(emailId);
				stopEmailProcessing(emailId);
				return;
			}
			emailPollingTimers.set(emailId, setTimeout(poll, emailPollIntervalMs));
		};

		void poll();
	}

	/** @param {any} email */
	async function handleReprocessEmail(email) {
		if (processingEmails.has(email.id) || emailPolling.has(email.id)) return;
		startEmailProcessing(email.id);
		try {
			const result = await queueEmailReprocess(email.id);
			if (result.error) {
				actionError = result.error.message;
				stopEmailProcessing(email.id);
				return;
			}
			const queued = result.data;
			if (!queued) {
				stopEmailProcessing(email.id);
				return;
			}
			emailHistory = emailHistory.map((item) =>
				item.id === email.id
					? { ...item, processing_status: queued.processing_status, processing_outcome: null }
					: item
			);
			pollEmailUntilTerminal(email.id);
		} catch (error) {
			actionError = error instanceof Error ? error.message : String(error);
			stopEmailProcessing(email.id);
		} finally {
			// The processing set is intentionally retained while polling. It is
			// cleared only on a terminal state, API error, or bounded timeout.
		}
	}

	/** @param {any} event */
	function isChangeEvent(event) {
		const sources = event.event_sources || [];
		return sources.some(
			/** @param {any} s */
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
		return formatChangeValue(value, $_('events.none'));
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
		const { senderKey, senderName, isPhotoSource } = resolveEventSender(event, {
			unknownSender: $_('history.unknownSender'),
			googlePhotos: $_('eventSource.googlePhotos'),
			googleCalendar: $_('integrations.googleCalendar')
		});
		if (isPhotoSource) {
			return $_('history.fromPhoto');
		}
		if (senderKey === 'google_calendar') {
			return $_('history.from', { values: { name: senderName } });
		}
		if (senderKey && senderKey !== $_('history.unknownSender') && senderName) {
			return $_('history.from', { values: { name: senderName } });
		}
		return '';
	}

	/** @param {string} eventId */
	function startProcessing(eventId) {
		processingEvents = new Set([...processingEvents, eventId]);
		actionError = '';
		forceUndoEvent = null;
	}

	/** @param {string} eventId */
	function stopProcessing(eventId) {
		const next = new Set(processingEvents);
		next.delete(eventId);
		processingEvents = next;
	}

	/**
	 * @param {any} event
	 * @param {{ force?: boolean }} [options]
	 */
	async function handleUndo(event, options = {}) {
		if (processingEvents.has(event.id)) return;
		startProcessing(event.id);
		try {
			const { error: undoError } = await undoHistoryEvent(event.id, options);
			if (undoError) {
				actionError = undoError.message;
				if (undoError.code === 'CALENDAR_DIVERGED' || undoError.status === 409) {
					forceUndoEvent = event;
				}
				return;
			}
			events = events.filter((e) => e.id !== event.id);
			totalCount--;
			forceUndoEvent = null;
		} finally {
			stopProcessing(event.id);
		}
	}

	async function handleForceUndo() {
		if (!forceUndoEvent) return;
		await handleUndo(forceUndoEvent, { force: true });
	}

	/** @param {any} event */
	async function handleRetry(event) {
		if (processingEvents.has(event.id)) return;
		startProcessing(event.id);
		try {
			const result = await syncEventToCalendar(event.id);
			if (result.error) {
				actionError = result.error.message;
				return;
			}
			events = events.map((e) => (e.id === event.id ? { ...e, status: 'synced' } : e));
		} finally {
			stopProcessing(event.id);
		}
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
{:else if loadError}
	<ErrorAlert message={loadError} onretry={loadEvents} />
{:else if events.length === 0 && emailHistory.length === 0}
	<EmptyState
		heading={$_('history.noActivity')}
		description={$_('history.noActivityDescription')}
	/>
{:else}
	{#if actionError}
		{#if forceUndoEvent}
			<ErrorAlert
				message={actionError}
				onaction={handleForceUndo}
				actionLabel={$_('history.forceUndo')}
			/>
		{:else}
			<ErrorAlert message={actionError} />
		{/if}
	{/if}
	<div class="space-y-6">
		{#each [...groupedByDate().entries()] as [dateLabel, dateEvents]}
			<div>
				<h2 class="text-sm font-semibold text-base-content/60 mb-3">{dateLabel}</h2>
				<div>
					{#each dateEvents as event (event.id)}
						{@const isProcessing = processingEvents.has(event.id)}
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
								{#if isProcessing}
									<span
										class="loading loading-spinner loading-sm"
										aria-label={$_('common.loading')}
										aria-live="polite"
									></span>
								{:else if event.status === 'sync_failed'}
									<button
										class="btn btn-outline btn-warning btn-xs"
										onclick={() => handleRetry(event)}
									>
										{$_('history.retrySync')}
									</button>
								{:else if ['approved', 'synced', 'rejected', 'cancelled'].includes(event.status)}
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

{#if !isLoading && (emailHistory.length > 0 || emailLoadError)}
	<section class="mt-10" aria-labelledby="email-history-heading">
		<div class="flex items-center justify-between mb-3">
			<h2 id="email-history-heading" class="text-lg font-semibold">{$_('history.emailHistory')}</h2>
			{#if emailHistoryCount > emailHistory.length}
				<span class="text-xs text-base-content/60">{emailHistory.length} / {emailHistoryCount}</span>
			{/if}
		</div>
		{#if emailLoadError}
			<ErrorAlert message={emailLoadError} />
		{:else}
			<div class="space-y-2">
				{#each emailHistory as email (email.id)}
					{@const emailBusy = processingEmails.has(email.id) || (['pending', 'processing'].includes(email.processing_status) && !emailTimedOut.has(email.id))}
					<div class="flex items-start justify-between gap-3 p-3 border border-base-200 rounded-lg">
						<div class="min-w-0 flex-1">
							<div class="flex items-center gap-2 flex-wrap">
								<span class="font-medium text-sm truncate">{email.subject || $_('eventSource.noSubject')}</span>
								<span class="badge badge-sm badge-outline">{email.email_provider === 'outlook' ? $_('integrations.outlook') : $_('integrations.gmail')}</span>
							</div>
							<div class="flex items-center gap-2 mt-1 text-xs text-base-content/60 flex-wrap">
								<span>{emailTime(email)}</span>
								<span>{emailSender(email)}</span>
								<span>·</span>
								<span>{emailOutcome(email)}</span>
							</div>
							{#if email.processing_explanation}
								<p class="text-xs text-base-content/70 mt-1">{email.processing_explanation}</p>
							{/if}
						</div>
						<button
							class="btn btn-outline btn-xs flex-shrink-0"
							disabled={emailBusy}
							onclick={() => handleReprocessEmail(email)}
						>
							{#if emailBusy}
								<span class="loading loading-spinner loading-xs"></span>
							{:else}
								{$_('history.reprocess')}
							{/if}
						</button>
					</div>
				{/each}
			</div>
			{#if emailHasMore}
				<div class="text-center py-4">
					<button class="btn btn-ghost" onclick={loadMoreEmailHistory} disabled={emailLoadingMore}>
						{#if emailLoadingMore}
							<span class="loading loading-spinner loading-sm"></span>
						{:else}
							{$_('history.loadMore')}
						{/if}
					</button>
				</div>
			{/if}
		{/if}
	</section>
{/if}
