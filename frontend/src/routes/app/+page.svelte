<script>
	import { onMount, onDestroy } from 'svelte';
	import { _ } from 'svelte-i18n';
	import { fetchIntegrations } from '$lib/services/integrations.js';
	import {
		fetchPendingEventsWithSources,
		updateEventStatus
	} from '$lib/services/events.js';
	import { createSenderRule, ignoreSenderRetroactive } from '$lib/services/sender-rules.js';
	import {
		applyEventChange,
		rejectEventChange,
		undoHistoryEvent,
		initiateGmailAuth,
		initiateOutlookAuth,
		initiateCalendarAuth
	} from '$lib/api/backend.js';
	import IntegrationStatus from '$lib/components/IntegrationStatus.svelte';
	import ConnectionRecovery from '$lib/components/ConnectionRecovery.svelte';
	import SenderHeader from '$lib/components/SenderHeader.svelte';
	import EventCard from '$lib/components/EventCard.svelte';
	import ChangeCard from '$lib/components/ChangeCard.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import ErrorAlert from '$lib/components/ErrorAlert.svelte';
	import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import ConfirmModal from '$lib/components/ConfirmModal.svelte';
	import InlineActionError from '$lib/components/InlineActionError.svelte';
	import { resolveEventSender } from '$lib/event-sender.js';
	import * as liveUpdates from '$lib/live-updates.js';
	import {
		createLaneOrder,
		seedLaneOrder,
		reconcileLaneOrder,
		sortLaneEvents
	} from '$lib/review-queue-order.js';
	import DispositionedCard from '$lib/components/DispositionedCard.svelte';
	import { flip } from 'svelte/animate';

	/** @type {any[]} */
	let integrationsList = $state([]);
	/** @type {any[]} */
	let events = $state([]);
	let isLoadingIntegrations = $state(true);
	let hasEventSnapshot = $state(false);
	let isInitialEventsLoad = $state(false);
	let isRefreshingEvents = $state(false);
	let refreshError = $state('');
	let refreshSequence = $state(0);
	let refreshQueued = $state(false);
	/** @type {Map<string, { event: any, kind: 'accept'|'reject', lane: string }>} */
	let dispositions = $state(new Map());
	let error = $state('');
	let oauthError = $state('');
	let bulkError = $state('');
	/** @type {Map<string, string>} */
	let eventErrors = $state(new Map());
	/** @type {Map<string, string>} */
	let senderErrors = $state(new Map());
	let integrationLoadFailed = $state(false);
	let notification = $state('');
	let liveAnnouncement = $state('');
	let processingEvents = $state(new Set());
	// Lane orders — session-stable ranks, never renumbered
	let newLaneOrder = $state(createLaneOrder());
	let changeLaneOrder = $state(createLaneOrder());
	// Derived from lane orders for grouping (stable)
	let newSenderOrder = $derived(newLaneOrder.senderRank);
	let changeSenderOrder = $derived(changeLaneOrder.senderRank);
	/** @type {{events: any[], timer: ReturnType<typeof setTimeout>} | null} */
	let rejectedUndo = $state(null);
	let undoingReject = $state(false);

	let gcalIntegration = $derived(
		integrationsList.find((i) => i.provider === 'google_calendar')
	);
	let calendarConnected = $derived(gcalIntegration?.status === 'active');
	let firstRun = $derived(integrationsList.length === 0);

	let newEvents = $derived(events.filter((e) => e.status === 'pending_review'));
	let changeEvents = $derived(events.filter((e) => e.status === 'pending_change'));

	/** @param {any} event */
	function senderForEvent(event) {
		return resolveEventSender(event, {
			unknownSender: $_('common.unknownSender'),
			googlePhotos: $_('eventSource.googlePhotos'),
			googleCalendar: $_('integrations.googleCalendar')
		});
	}

	// captureSenderOrder is now handled by seedLaneOrder/reconcileLaneOrder in review-queue-order.js
	// Kept for backwards compat if referenced, but new code uses LaneOrder.

	/** @param {any[]} list @param {Map<any, any>} stableOrder */
	function groupBySender(list, stableOrder) {
		const senderMap = new Map();
		for (const event of list) {
			const { senderKey, senderName } = senderForEvent(event);

			if (!senderMap.has(senderKey)) {
				senderMap.set(senderKey, {
					sender: senderKey,
					senderName: senderName,
					events: []
				});
			}

			senderMap.get(senderKey).events.push(event);
		}
		return new Map(
			[...senderMap.entries()].sort(
				([left], [right]) =>
					(stableOrder.get(left) ?? Number.MAX_SAFE_INTEGER) -
					(stableOrder.get(right) ?? Number.MAX_SAFE_INTEGER)
			)
		);
	}

	let groupedNew = $derived(groupBySender(newEvents, newSenderOrder));
	let groupedChanges = $derived(groupBySender(changeEvents, changeSenderOrder));

	/** @param {string} eventId @param {string} message */
	function setEventError(eventId, message) {
		const next = new Map(eventErrors);
		if (message) next.set(eventId, message);
		else next.delete(eventId);
		eventErrors = next;
	}

	/** @param {string} sender @param {string} message */
	function setSenderError(sender, message) {
		const next = new Map(senderErrors);
		if (message) next.set(sender, message);
		else next.delete(sender);
		senderErrors = next;
	}

	function clearRejectUndoTimer() {
		if (rejectedUndo?.timer) clearTimeout(rejectedUndo.timer);
	}

	function dismissRejectUndo() {
		clearRejectUndoTimer();
		rejectedUndo = null;
	}

	/** @param {any[]} newlyRejected */
	function showRejectUndo(newlyRejected) {
		if (!newlyRejected || newlyRejected.length === 0) return;
		clearRejectUndoTimer();
		const existing = rejectedUndo?.events ?? [];
		const combined = [...existing, ...newlyRejected];
		const timer = setTimeout(() => {
			rejectedUndo = null;
		}, 8000);
		rejectedUndo = { events: combined, timer };
	}

	async function handleUndoRejected() {
		if (!rejectedUndo || undoingReject) return;
		const toRestore = rejectedUndo.events;
		clearRejectUndoTimer();
		rejectedUndo = null;
		undoingReject = true;
		// Clear dispositions for undone events so loadEvents does not filter them
		if (dispositions.size > 0) {
			let cleared = false;
			for (const ev of toRestore) {
				if (dispositions.has(ev.id)) { dispositions.delete(ev.id); cleared = true; }
			}
			if (cleared) dispositions = new Map(dispositions);
		}
		// Optimistically reinsert events in stable order (retain original rank for Undo)
		const idsInEvents = new Set(events.map((e) => e.id));
		const toReinsert = toRestore.filter((e) => !idsInEvents.has(e.id));
		if (toReinsert.length > 0) {
			events = [...events, ...toReinsert];
			// Re-apply stable lane sorting so Undo restores exact position
			const newEvents_undo = events.filter((e) => e.status === 'pending_review');
			const changeEvents_undo = events.filter((e) => e.status === 'pending_change');
			events = [...sortLaneEvents(newEvents_undo, newLaneOrder, senderForEvent), ...sortLaneEvents(changeEvents_undo, changeLaneOrder, senderForEvent)];
			// Ensure lane orders contain restored senders/events for stable grouping (retain rank)
			for (const ev of toReinsert) {
				const { senderKey } = senderForEvent(ev);
				const lane = ev.status === 'pending_change' ? changeLaneOrder : newLaneOrder;
				if (!lane.senderRank.has(senderKey)) {
					lane.senderRank.set(senderKey, lane.nextSenderRank++);
				}
				if (!lane.eventRank.has(ev.id)) {
					lane.eventRank.set(ev.id, lane.nextEventRank++);
				}
			}
			newLaneOrder = { ...newLaneOrder, senderRank: new Map(newLaneOrder.senderRank), eventRank: new Map(newLaneOrder.eventRank) };
			changeLaneOrder = { ...changeLaneOrder, senderRank: new Map(changeLaneOrder.senderRank), eventRank: new Map(changeLaneOrder.eventRank) };
		}
		let hadError = false;
		for (const ev of toRestore) {
			const { error } = await undoHistoryEvent(ev.id);
			if (error) {
				hadError = true;
				setEventError(ev.id, error.message);
				// Remove optimistically restored event on failure
				events = events.filter((e) => e.id !== ev.id);
			} else {
				setEventError(ev.id, '');
			}
		}
		undoingReject = false;
		if (hadError) {
			await loadEvents();
		} else {
			// Refresh to ensure server state (status already pending, but ensures ordering)
			await loadEvents();
		}
	}

	onMount(() => {
		let cleanup = () => {};
		void (async () => {
		const params = new URLSearchParams(window.location.search);
		const oauth = params.get('oauth');
		if (oauth === 'success') {
			notification = $_('integrations.connected');
			setTimeout(() => {
				notification = '';
			}, 4000);
			window.history.replaceState({}, '', '/app');
		} else if (oauth === 'error') {
			oauthError = params.get('message') || $_('integrations.connectFailed');
			window.history.replaceState({}, '', '/app');
		}
			await loadIntegrations();

		// Live UI: subscribe to invalidations for events/event_sources/integrations
		const unsubEvents = liveUpdates.subscribe('events', async () => {
			if (processingEvents.size === 0) {
				await loadEvents();
			} else {
				// Defer refresh until optimistic mutations complete — preserve optimistic removals
				setTimeout(() => { if (processingEvents.size === 0) loadEvents(); }, 500);
			}
		});
		const unsubSources = liveUpdates.subscribe('event_sources', async () => {
			if (processingEvents.size === 0) await loadEvents();
		});
		const unsubIntegrations = liveUpdates.subscribe('integrations', async () => {
			await loadIntegrations();
		});

		cleanup = () => {
			unsubEvents();
			unsubSources();
			unsubIntegrations();
			clearRejectUndoTimer();
		};
		})();
		return () => cleanup();
	});

	onDestroy(() => clearRejectUndoTimer());

	async function loadIntegrations() {
		isLoadingIntegrations = true;
		integrationLoadFailed = false;
		const result = await fetchIntegrations();
		if (result.error) {
			error = result.error.message;
			integrationLoadFailed = true;
			isLoadingIntegrations = false;
			return;
		} else {
			integrationsList = result.data;
		}
		isLoadingIntegrations = false;

		await loadEvents();
	}

	async function loadEvents() {
		const isFirst = !hasEventSnapshot;
		if (!isFirst && isRefreshingEvents) {
			refreshQueued = true;
			return;
		}
		const seq = ++refreshSequence;
		if (isFirst) {
			isInitialEventsLoad = true;
		} else {
			isRefreshingEvents = true;
		}
		error = '';
		refreshError = '';
		try {
			const result = await fetchPendingEventsWithSources();
			// Ignore stale responses and drop only their data. The current request
			// remains responsible for the loading flags and queued refresh.
			if (seq !== refreshSequence) return;
			if (result.error) {
				if (isFirst) error = result.error.message;
				else refreshError = result.error.message;
				return;
			}
			const serverEvents = result.data;
			const serverIds = new Set(serverEvents.map((event) => event.id));
			// Do not reinsert dispositions that are still pending server confirmation.
			const dispositionIds = new Set(dispositions.keys());
			const loadedEvents = serverEvents.filter((event) => !dispositionIds.has(event.id));
			const newLoaded = loadedEvents.filter((event) => event.status === 'pending_review');
			const changeLoaded = loadedEvents.filter((event) => event.status === 'pending_change');
			if (!hasEventSnapshot) {
				newLaneOrder = seedLaneOrder(newLoaded, senderForEvent);
				changeLaneOrder = seedLaneOrder(changeLoaded, senderForEvent);
				hasEventSnapshot = true;
			} else {
				reconcileLaneOrder(newLaneOrder, newLoaded, senderForEvent);
				reconcileLaneOrder(changeLaneOrder, changeLoaded, senderForEvent);
				// Trigger reactivity — maps were mutated.
				newLaneOrder = { ...newLaneOrder, senderRank: new Map(newLaneOrder.senderRank), eventRank: new Map(newLaneOrder.eventRank) };
				changeLaneOrder = { ...changeLaneOrder, senderRank: new Map(changeLaneOrder.senderRank), eventRank: new Map(changeLaneOrder.eventRank) };
			}
			const sortedNew = sortLaneEvents(newLoaded, newLaneOrder, senderForEvent);
			const sortedChange = sortLaneEvents(changeLoaded, changeLaneOrder, senderForEvent);
			events = [...sortedNew, ...sortedChange];

			// Tombstones are based on the unfiltered server snapshot. A
			// dispositioned row still returned by the server is not confirmed gone.
			let changed = false;
			for (const id of dispositions.keys()) {
				if (!serverIds.has(id)) {
					dispositions.delete(id);
					changed = true;
				}
			}
			if (changed) dispositions = new Map(dispositions);
		} finally {
			if (isFirst) isInitialEventsLoad = false;
			else if (seq === refreshSequence) isRefreshingEvents = false;
			if (seq === refreshSequence && refreshQueued) {
				refreshQueued = false;
				queueMicrotask(() => loadEvents());
			}
		}
	}

	/** @param {any} event */
	async function handleApproveNew(event) {
		if (!calendarConnected) {
			setEventError(event.id, $_('integrations.calendarRequiredToAccept'));
			return;
		}
		if (processingEvents.has(event.id)) return;
		setEventError(event.id, '');
		processingEvents = new Set([...processingEvents, event.id]);
		dispositions = new Map(dispositions).set(event.id, { event, kind: 'accept', lane: 'pending_review' });
		const previous = events;
		events = events.filter((e) => e.id !== event.id);
		try {
			const { error: updateError } = await updateEventStatus(event.id, 'approved');
			if (updateError) {
				events = previous;
				dispositions = new Map([...dispositions].filter(([k]) => k !== event.id));
				setEventError(event.id, updateError.message);
				return;
			}
			liveAnnouncement = $_('review.accepted', { values: { count: newEvents.length } });
			setTimeout(() => (liveAnnouncement = ''), 3000);
		} finally {
			const next = new Set(processingEvents);
			next.delete(event.id);
			processingEvents = next;
		}
	}

	/** @param {any} event */
	async function handleRejectNew(event) {
		if (processingEvents.has(event.id)) return;
		setEventError(event.id, '');
		processingEvents = new Set([...processingEvents, event.id]);
		dispositions = new Map(dispositions).set(event.id, { event, kind: 'reject', lane: 'pending_review' });
		const previous = events;
		events = events.filter((e) => e.id !== event.id);
		try {
			const { error: updateError } = await updateEventStatus(event.id, 'rejected');
			if (updateError) {
				events = previous;
				dispositions = new Map([...dispositions].filter(([k]) => k !== event.id));
				setEventError(event.id, updateError.message);
				return;
			}
			liveAnnouncement = $_('review.rejected', { values: { count: newEvents.length } });
			setTimeout(() => (liveAnnouncement = ''), 3000);
			showRejectUndo([event]);
		} finally {
			const next = new Set(processingEvents);
			next.delete(event.id);
			processingEvents = next;
		}
	}

	/** @param {any} event */
	async function handleApproveChange(event) {
		if (!calendarConnected) {
			setEventError(event.id, $_('integrations.calendarRequiredToAccept'));
			return;
		}
		if (processingEvents.has(event.id)) return;
		setEventError(event.id, '');
		processingEvents = new Set([...processingEvents, event.id]);
		const previous = events;
		events = events.filter((e) => e.id !== event.id);
		try {
			const { error: applyError } = await applyEventChange(event.id);
			if (applyError) {
				events = previous;
				setEventError(event.id, applyError.message);
				return;
			}
			liveAnnouncement = $_('review.accepted', { values: { count: changeEvents.length } });
		} finally {
			const next = new Set(processingEvents);
			next.delete(event.id);
			processingEvents = next;
		}
	}

	/** @param {any} event */
	async function handleRejectChange(event) {
		if (processingEvents.has(event.id)) return;
		setEventError(event.id, '');
		processingEvents = new Set([...processingEvents, event.id]);
		const previous = events;
		events = events.filter((e) => e.id !== event.id);
		try {
			const { error: rejectError } = await rejectEventChange(event.id);
			if (rejectError) {
				events = previous;
				setEventError(event.id, rejectError.message);
				return;
			}
			liveAnnouncement = $_('review.rejected', { values: { count: changeEvents.length } });
			showRejectUndo([event]);
		} finally {
			const next = new Set(processingEvents);
			next.delete(event.id);
			processingEvents = next;
		}
	}

	/** @param {any[]} eventsList */
	async function handleApproveAllNew(eventsList) {
		if (!calendarConnected) {
			bulkError = $_('integrations.calendarRequiredToAccept');
			return;
		}
		for (const event of eventsList) {
			await handleApproveNew(event);
		}
	}

	let acceptAllConfirmOpen = $state(false);

	async function handleApproveAll() {
		if (!calendarConnected) {
			bulkError = $_('integrations.calendarRequiredToAccept');
			return;
		}
		acceptAllConfirmOpen = false;
		await handleApproveAllNew(newEvents);
		for (const event of changeEvents) {
			await handleApproveChange(event);
		}
	}

	/** @param {any[]} eventsList */
	async function handleRejectAllNew(eventsList) {
		const rejected = [];
		for (const event of eventsList) {
			if (processingEvents.has(event.id)) continue;
			setEventError(event.id, '');
			processingEvents = new Set([...processingEvents, event.id]);
			const previous = events;
			events = events.filter((e) => e.id !== event.id);
			const { error: updateError } = await updateEventStatus(event.id, 'rejected');
			const next = new Set(processingEvents);
			next.delete(event.id);
			processingEvents = next;
			if (updateError) {
				events = previous;
				setEventError(event.id, updateError.message);
			} else {
				rejected.push(event);
			}
		}
		if (rejected.length > 0) showRejectUndo(rejected);
	}

	/** @param {any[]} eventsList */
	async function handleRejectAllChange(eventsList) {
		const rejected = [];
		for (const event of eventsList) {
			if (processingEvents.has(event.id)) continue;
			setEventError(event.id, '');
			processingEvents = new Set([...processingEvents, event.id]);
			const previous = events;
			events = events.filter((e) => e.id !== event.id);
			const { error: rejectError } = await rejectEventChange(event.id);
			const next = new Set(processingEvents);
			next.delete(event.id);
			processingEvents = next;
			if (rejectError) {
				events = previous;
				setEventError(event.id, rejectError.message);
			} else {
				rejected.push(event);
			}
		}
		if (rejected.length > 0) showRejectUndo(rejected);
	}

	/**
	 * Ignore a sender retroactively: rejects their pending New-lane events AND
	 * discards their Changes-lane proposals in one atomic server-side call.
	 * @param {string} senderEmail
	 */
	async function handleIgnoreSender(senderEmail) {
		setSenderError(senderEmail, '');
		if (!senderEmail.includes('@')) {
			setSenderError(senderEmail, $_('home.senderIgnoreInvalidSender'));
			return;
		}
		const { error: rpcError } = await ignoreSenderRetroactive(senderEmail);
		if (rpcError) {
			setSenderError(senderEmail, rpcError.message);
			return;
		}
		await loadEvents();
		notification = $_('home.senderIgnored', { values: { senderEmail } });
		setTimeout(() => {
			notification = '';
		}, 3000);
	}

	/**
	 * @param {string} senderEmail
	 * @param {any[]} eventsList
	 */
	async function handleAutoApproveSender(senderEmail, eventsList) {
		if (!calendarConnected) {
			setSenderError(senderEmail, $_('integrations.calendarRequiredToAccept'));
			return;
		}
		setSenderError(senderEmail, '');
		const { error: ruleError } = await createSenderRule({
			sender_email: senderEmail,
			action: 'auto_approve'
		});
		if (ruleError) {
			setSenderError(senderEmail, ruleError.message);
			return;
		}
		for (const event of eventsList) {
			if (event.status === 'pending_change') {
				await handleApproveChange(event);
			} else {
				await handleApproveNew(event);
			}
		}
		notification = $_('home.senderAutoApproved', { values: { senderEmail } });
		setTimeout(() => {
			notification = '';
		}, 3000);
	}

	async function handleConnect() {
		await initiateGmailAuth();
	}

	/** @param {string} provider */
	async function handleAuthorize(provider) {
		if (provider === 'gmail') {
			await initiateGmailAuth();
		} else if (provider === 'outlook') {
			await initiateOutlookAuth();
		} else if (provider === 'google_calendar') {
			await initiateCalendarAuth();
		}
	}
</script>

<svelte:head>
	<title>{$_('home.title')}</title>
</svelte:head>

{#if notification}
	<div class="toast toast-end z-50">
		<div class="alert alert-success">
			<span>{notification}</span>
		</div>
	</div>
{/if}

{#if oauthError}
	<div class="toast toast-end z-50">
		<div class="alert alert-error max-w-md items-start" role="alert">
			<p>{oauthError}</p>
			<button
				class="btn action-tertiary"
				onclick={() => {
					oauthError = '';
				}}
			>{$_('common.dismiss')}</button>
		</div>
	</div>
{/if}

{#if isLoadingIntegrations}
	<LoadingSpinner />
{:else if integrationLoadFailed}
	<ErrorAlert message={error} onretry={loadIntegrations} />
{:else if firstRun}
	<IntegrationStatus
		integrations={integrationsList}
		setupMode={true}
		onconnect={handleConnect}
		onauthorize={handleAuthorize}
	/>
{:else if !hasEventSnapshot && isInitialEventsLoad}
	<div class="review-surface mx-auto w-full max-w-[var(--review-max-width)] px-[var(--screen-gutter)]">
		<div class="space-y-4" aria-busy="true" aria-live="polite">
			<span class="sr-only">{$_('common.loadingEvents')}</span>
			<div class="h-8 bg-base-200 rounded animate-pulse w-48"></div>
			<div class="h-24 bg-base-200 rounded animate-pulse"></div>
			<div class="h-24 bg-base-200 rounded animate-pulse"></div>
			<div class="h-24 bg-base-200 rounded animate-pulse"></div>
		</div>
	</div>
{:else if error}
	<div class="review-surface mx-auto w-full max-w-[var(--review-max-width)] px-[var(--screen-gutter)]">
		<ConnectionRecovery integrations={integrationsList} onauthorize={handleAuthorize} />
		<ErrorAlert message={error} onretry={loadEvents} />
	</div>
{:else if events.length === 0}
	<div class="review-surface mx-auto w-full max-w-[var(--review-max-width)] px-[var(--screen-gutter)]">
		<ConnectionRecovery integrations={integrationsList} onauthorize={handleAuthorize} />
		<div tabindex="-1" data-review-empty-focus>
			<EmptyState heading={$_('home.allCaughtUp')} description={$_('home.allCaughtUpDescription')} />
		</div>
	</div>
{:else}
	<div class="review-surface mx-auto w-full max-w-[var(--review-max-width)] px-[var(--screen-gutter)]" aria-busy={isRefreshingEvents ? 'true' : 'false'}>
		{#if refreshError}
			<div class="alert alert-warning mb-4" role="alert">
				<span>{refreshError}</span>
				<button class="btn btn-ghost btn-xs" onclick={() => loadEvents()}>Retry</button>
			</div>
		{/if}
		{#if isRefreshingEvents}
			<div class="sr-only" aria-live="polite">Refreshing</div>
		{/if}
		<div class="sr-only" role="status" aria-live="polite" aria-atomic="true">{liveAnnouncement}</div>
		<ConnectionRecovery integrations={integrationsList} onauthorize={handleAuthorize} />
		<PageHeader title={$_('nav.review')} subtitle={$_('home.subtitle')}>
			{#snippet children()}
				<button class="btn btn-primary rounded-[14px] shadow-brand" disabled={!calendarConnected} onclick={() => (acceptAllConfirmOpen = true)}>
					<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="m5 12 4 4L19 6" /></svg>
					{$_('home.acceptAll')}
				</button>
			{/snippet}
		</PageHeader>
		<InlineActionError message={bulkError} ondismiss={() => (bulkError = '')} />
		<div class="space-y-10">
		{#if newEvents.length > 0}
			<section>
				<div class="mb-4 flex items-end justify-between gap-3">
					<div><h2 class="text-xl font-extrabold">{$_('home.newSection')}</h2><p class="mt-1 text-sm text-base-content/60">{$_('home.newSectionDescription')}</p></div>
					<span class="badge badge-new badge-sm">{newEvents.length}</span>
				</div>
				<div class="review-sender-groups grid gap-5">
					{#each [...groupedNew.entries()] as [senderKey, senderGroup] (senderKey)}
						<div class="warm-card overflow-hidden">
							<SenderHeader
								sender={senderGroup.senderName}
								senderEmail={senderKey}
								eventCount={senderGroup.events.length}
								isPhotoSource={senderKey === 'google_photos'}
								canApprove={calendarConnected}
								error={senderErrors.get(senderKey) || ''}
								onapproveAll={() => handleApproveAllNew(senderGroup.events)}
								onrejectAll={() => handleRejectAllNew(senderGroup.events)}
								onignoreSender={() => handleIgnoreSender(senderKey)}
								onautoApproveSender={() =>
									handleAutoApproveSender(senderKey, senderGroup.events)}
							/>
							{#each senderGroup.events as event (event.id)}
								<div animate:flip={{ duration: 180 }}>
									<DispositionedCard {event} kind={dispositions.get(event.id)?.kind}>
										{#snippet children()}
										<EventCard
											{event}
											error={eventErrors.get(event.id) || ''}
											isProcessing={processingEvents.has(event.id)}
											canApprove={calendarConnected}
											onapprove={handleApproveNew}
											onreject={handleRejectNew}
										/>
										{/snippet}
									</DispositionedCard>
								</div>
							{/each}
						</div>
					{/each}
				</div>
			</section>
		{/if}

		{#if changeEvents.length > 0}
			<section>
				<div class="mb-4 flex items-end justify-between gap-3">
					<div><h2 class="text-xl font-extrabold">{$_('home.changesSection')}</h2><p class="mt-1 text-sm text-base-content/60">{$_('home.changesSectionDescription')}</p></div>
					<span class="badge badge-changed badge-sm">{changeEvents.length}</span>
				</div>
				<div class="review-sender-groups grid gap-5">
					{#each [...groupedChanges.entries()] as [senderKey, senderGroup] (senderKey)}
						<div class="warm-card overflow-hidden">
							<SenderHeader
								sender={senderGroup.senderName}
								senderEmail={senderKey}
								eventCount={senderGroup.events.length}
								isPhotoSource={senderKey === 'google_photos'}
								canApprove={calendarConnected}
								error={senderErrors.get(senderKey) || ''}
								onapproveAll={() => {
									for (const event of senderGroup.events) handleApproveChange(event);
								}}
								onrejectAll={() => handleRejectAllChange(senderGroup.events)}
								onignoreSender={() => handleIgnoreSender(senderKey)}
								onautoApproveSender={() =>
									handleAutoApproveSender(senderKey, senderGroup.events)}
							/>
							{#each senderGroup.events as event (event.id)}
								<div animate:flip={{ duration: 180 }}>
									<DispositionedCard {event} kind={dispositions.get(event.id)?.kind}>
										{#snippet children()}
										<ChangeCard
											{event}
											error={eventErrors.get(event.id) || ''}
											isProcessing={processingEvents.has(event.id)}
											canApprove={calendarConnected}
											onapprove={handleApproveChange}
											onreject={handleRejectChange}
										/>
										{/snippet}
									</DispositionedCard>
								</div>
							{/each}
						</div>
					{/each}
				</div>
			</section>
		{/if}
		<div class="flex gap-2 pt-1 sm:hidden">
			<button class="btn btn-primary min-h-12 flex-1 rounded-[14px] shadow-brand" disabled={!calendarConnected} onclick={() => (acceptAllConfirmOpen = true)}>
				<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="m5 12 4 4L19 6" /></svg>
				{$_('home.acceptAll')}
			</button>
		</div>
		</div>
	</div>
{/if}
{#if rejectedUndo}
	<div class="toast toast-bottom toast-center z-50" role="status" aria-live="polite">
		<div class="alert bg-base-100 shadow-lg border border-base-300 gap-3 max-w-md">
			<span class="text-sm font-medium">
				{#if rejectedUndo.events.length === 1}
					{$_('home.eventRejected')}
				{:else}
					{$_('home.eventsRejected', { values: { count: rejectedUndo.events.length } })}
				{/if}
			</span>
			<button
				class="btn btn-sm btn-primary"
				disabled={undoingReject}
				onclick={handleUndoRejected}
			>
				{#if undoingReject}
					<span class="loading loading-spinner loading-xs"></span>
				{/if}
				{$_('history.undo')}
			</button>
			<button
				class="btn btn-ghost btn-sm btn-circle"
				onclick={dismissRejectUndo}
				aria-label={$_('common.dismiss')}
			>
				✕
			</button>
		</div>
	</div>
{/if}
<ConfirmModal
	open={acceptAllConfirmOpen}
	title={$_('home.acceptAll')}
	description={$_('home.acceptAllConfirm', { values: { count: newEvents.length + changeEvents.length } })}
	confirmText={$_('home.acceptAll')}
	confirmClass="btn-primary"
	onconfirm={handleApproveAll}
	oncancel={() => (acceptAllConfirmOpen = false)}
/>
