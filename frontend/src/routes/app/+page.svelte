<script>
	import { onMount } from 'svelte';
	import { _ } from 'svelte-i18n';
	import { fetchIntegrations } from '$lib/services/integrations.js';
	import {
		fetchPendingEventsWithSources,
		updateEventStatus
	} from '$lib/services/events.js';
	import { createSenderRule } from '$lib/services/sender-rules.js';
	import {
		applyEventChange,
		rejectEventChange,
		syncEventToCalendar,
		initiateGmailAuth,
		initiateOutlookAuth,
		initiateCalendarAuth,
		initiatePhotosAuth
	} from '$lib/api/backend.js';
	import IntegrationStatus from '$lib/components/IntegrationStatus.svelte';
	import SenderHeader from '$lib/components/SenderHeader.svelte';
	import EventCard from '$lib/components/EventCard.svelte';
	import ChangeCard from '$lib/components/ChangeCard.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import ErrorAlert from '$lib/components/ErrorAlert.svelte';
	import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
	import { resolveEventSender } from '$lib/event-sender.js';

	/** @type {any[]} */
	let integrationsList = $state([]);
	/** @type {any[]} */
	let events = $state([]);
	let isLoadingIntegrations = $state(true);
	let isLoadingEvents = $state(false);
	let error = $state('');
	/** Action-level error that does not hide the review list */
	let actionError = $state('');
	let notification = $state('');
	let processingEvents = $state(new Set());

	let gmailIntegration = $derived(integrationsList.find((i) => i.provider === 'gmail'));
	let outlookIntegration = $derived(integrationsList.find((i) => i.provider === 'outlook'));
	let gcalIntegration = $derived(
		integrationsList.find((i) => i.provider === 'google_calendar')
	);
	let emailConnected = $derived(
		gmailIntegration?.status === 'active' || outlookIntegration?.status === 'active'
	);
	let fullyConnected = $derived(emailConnected && gcalIntegration?.status === 'active');

	let newEvents = $derived(events.filter((e) => e.status === 'pending_review'));
	let changeEvents = $derived(events.filter((e) => e.status === 'pending_change'));

	/** @param {any[]} list */
	function groupBySender(list) {
		const senderMap = new Map();
		for (const event of list) {
			const { senderKey, senderName } = resolveEventSender(event, {
				unknownSender: $_('common.unknownSender'),
				googlePhotos: $_('integrations.googlePhotos'),
				googleCalendar: $_('integrations.googleCalendar')
			});

			if (!senderMap.has(senderKey)) {
				senderMap.set(senderKey, {
					sender: senderKey,
					senderName: senderName,
					events: []
				});
			}

			senderMap.get(senderKey).events.push(event);
		}
		return senderMap;
	}

	let groupedNew = $derived(groupBySender(newEvents));
	let groupedChanges = $derived(groupBySender(changeEvents));

	onMount(async () => {
		const params = new URLSearchParams(window.location.search);
		const oauth = params.get('oauth');
		if (oauth === 'success') {
			notification = $_('integrations.connected');
			setTimeout(() => {
				notification = '';
			}, 4000);
			window.history.replaceState({}, '', '/app');
		} else if (oauth === 'error') {
			error = params.get('message') || $_('integrations.connectFailed');
			window.history.replaceState({}, '', '/app');
		}
		await loadIntegrations();
	});

	async function loadIntegrations() {
		isLoadingIntegrations = true;
		const result = await fetchIntegrations();
		if (result.error) {
			error = result.error.message;
		} else {
			integrationsList = result.data;
		}
		isLoadingIntegrations = false;

		if (
			(integrationsList.find((i) => i.provider === 'gmail')?.status === 'active' ||
				integrationsList.find((i) => i.provider === 'outlook')?.status === 'active') &&
			integrationsList.find((i) => i.provider === 'google_calendar')?.status === 'active'
		) {
			await loadEvents();
		}
	}

	async function loadEvents() {
		isLoadingEvents = true;
		error = '';
		const result = await fetchPendingEventsWithSources();
		if (result.error) {
			error = result.error.message;
		} else {
			events = result.data;
		}
		isLoadingEvents = false;
	}

	/** @param {any} event */
	async function handleApproveNew(event) {
		if (processingEvents.has(event.id)) return;
		actionError = '';
		processingEvents = new Set([...processingEvents, event.id]);
		const previous = events;
		// Optimistic remove so the card does not linger while the request is in flight
		events = events.filter((e) => e.id !== event.id);
		try {
			const { error: updateError } = await updateEventStatus(event.id, 'approved');
			if (updateError) {
				events = previous;
				actionError = updateError.message;
				return;
			}
			try {
				await syncEventToCalendar(event.id);
			} catch (syncError) {
				console.error('Calendar sync failed after approval:', syncError);
				actionError = $_('home.syncFailedAfterApprove');
			}
		} finally {
			const next = new Set(processingEvents);
			next.delete(event.id);
			processingEvents = next;
		}
	}

	/** @param {any} event */
	async function handleRejectNew(event) {
		if (processingEvents.has(event.id)) return;
		actionError = '';
		processingEvents = new Set([...processingEvents, event.id]);
		const previous = events;
		events = events.filter((e) => e.id !== event.id);
		try {
			const { error: updateError } = await updateEventStatus(event.id, 'rejected');
			if (updateError) {
				events = previous;
				actionError = updateError.message;
				return;
			}
		} finally {
			const next = new Set(processingEvents);
			next.delete(event.id);
			processingEvents = next;
		}
	}

	/** @param {any} event */
	async function handleApproveChange(event) {
		if (processingEvents.has(event.id)) return;
		actionError = '';
		processingEvents = new Set([...processingEvents, event.id]);
		const previous = events;
		events = events.filter((e) => e.id !== event.id);
		try {
			const { error: applyError } = await applyEventChange(event.id);
			if (applyError) {
				events = previous;
				actionError = applyError.message;
				return;
			}
			try {
				await syncEventToCalendar(event.id);
			} catch (syncError) {
				console.error('Calendar sync failed after change apply:', syncError);
				actionError = $_('home.syncFailedAfterApprove');
			}
		} finally {
			const next = new Set(processingEvents);
			next.delete(event.id);
			processingEvents = next;
		}
	}

	/** @param {any} event */
	async function handleRejectChange(event) {
		if (processingEvents.has(event.id)) return;
		actionError = '';
		processingEvents = new Set([...processingEvents, event.id]);
		const previous = events;
		events = events.filter((e) => e.id !== event.id);
		try {
			const { error: rejectError } = await rejectEventChange(event.id);
			if (rejectError) {
				events = previous;
				actionError = rejectError.message;
				return;
			}
		} finally {
			const next = new Set(processingEvents);
			next.delete(event.id);
			processingEvents = next;
		}
	}

	/** @param {any[]} eventsList */
	async function handleApproveAllNew(eventsList) {
		for (const event of eventsList) {
			await handleApproveNew(event);
		}
	}

	/** @param {any[]} eventsList */
	async function handleRejectAllNew(eventsList) {
		for (const event of eventsList) {
			await handleRejectNew(event);
		}
	}

	/**
	 * @param {string} senderEmail
	 * @param {any[]} eventsList
	 */
	async function handleIgnoreSender(senderEmail, eventsList) {
		const { error: ruleError } = await createSenderRule({
			sender_email: senderEmail,
			action: 'ignore'
		});
		if (ruleError) {
			error = ruleError.message;
			return;
		}
		for (const event of eventsList) {
			if (event.status === 'pending_change') {
				await handleRejectChange(event);
			} else {
				await handleRejectNew(event);
			}
		}
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
		const { error: ruleError } = await createSenderRule({
			sender_email: senderEmail,
			action: 'auto_approve'
		});
		if (ruleError) {
			error = ruleError.message;
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
		} else if (provider === 'google_photos') {
			await initiatePhotosAuth();
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

{#if isLoadingIntegrations}
	<LoadingSpinner />
{:else if !fullyConnected}
	<IntegrationStatus
		integrations={integrationsList}
		setupMode={true}
		onconnect={handleConnect}
		onauthorize={handleAuthorize}
	/>
{:else if isLoadingEvents}
	<div class="space-y-4" aria-busy="true" aria-live="polite">
		<span class="sr-only">{$_('common.loadingEvents')}</span>
		<div class="h-8 bg-base-200 rounded animate-pulse w-48"></div>
		<div class="h-24 bg-base-200 rounded animate-pulse"></div>
		<div class="h-24 bg-base-200 rounded animate-pulse"></div>
		<div class="h-24 bg-base-200 rounded animate-pulse"></div>
	</div>
{:else if error}
	<ErrorAlert message={error} onretry={loadEvents} />
{:else if events.length === 0}
	<EmptyState heading={$_('home.allCaughtUp')} description={$_('home.allCaughtUpDescription')} />
{:else}
	{#if actionError}
		<div class="alert alert-error mb-4" role="alert">
			<span>{actionError}</span>
			<button class="btn btn-sm btn-ghost" onclick={() => (actionError = '')}>{$_('common.dismiss')}</button>
		</div>
	{/if}
	<div class="space-y-10">
		{#if newEvents.length > 0}
			<section>
				<h2 class="text-lg font-semibold mb-1">{$_('home.newSection')}</h2>
				<p class="text-sm text-base-content/60 mb-4">{$_('home.newSectionDescription')}</p>
				<div class="space-y-6">
					{#each [...groupedNew.entries()] as [senderKey, senderGroup]}
						<div>
							<SenderHeader
								sender={senderGroup.senderName}
								senderEmail={senderKey}
								eventCount={senderGroup.events.length}
								isPhotoSource={senderKey === 'google_photos'}
								onapproveAll={() => handleApproveAllNew(senderGroup.events)}
								onrejectAll={() => handleRejectAllNew(senderGroup.events)}
								onignoreSender={() => handleIgnoreSender(senderKey, senderGroup.events)}
								onautoApproveSender={() =>
									handleAutoApproveSender(senderKey, senderGroup.events)}
							/>
							{#each senderGroup.events as event (event.id)}
								<EventCard
									{event}
									isProcessing={processingEvents.has(event.id)}
									onapprove={handleApproveNew}
									onreject={handleRejectNew}
								/>
							{/each}
						</div>
					{/each}
				</div>
			</section>
		{/if}

		{#if changeEvents.length > 0}
			<section>
				<h2 class="text-lg font-semibold mb-1">{$_('home.changesSection')}</h2>
				<p class="text-sm text-base-content/60 mb-4">{$_('home.changesSectionDescription')}</p>
				<div class="space-y-6">
					{#each [...groupedChanges.entries()] as [senderKey, senderGroup]}
						<div>
							<SenderHeader
								sender={senderGroup.senderName}
								senderEmail={senderKey}
								eventCount={senderGroup.events.length}
								isPhotoSource={senderKey === 'google_photos'}
								onapproveAll={() => {
									for (const event of senderGroup.events) handleApproveChange(event);
								}}
								onrejectAll={() => {
									for (const event of senderGroup.events) handleRejectChange(event);
								}}
								onignoreSender={() => handleIgnoreSender(senderKey, senderGroup.events)}
								onautoApproveSender={() =>
									handleAutoApproveSender(senderKey, senderGroup.events)}
							/>
							{#each senderGroup.events as event (event.id)}
								<ChangeCard
									{event}
									isProcessing={processingEvents.has(event.id)}
									onapprove={handleApproveChange}
									onreject={handleRejectChange}
								/>
							{/each}
						</div>
					{/each}
				</div>
			</section>
		{/if}
	</div>
{/if}
