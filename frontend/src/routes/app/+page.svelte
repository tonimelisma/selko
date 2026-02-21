<script>
	import { onMount } from 'svelte';
	import { _ } from 'svelte-i18n';
	import { fetchIntegrations } from '$lib/services/integrations.js';
	import {
		fetchPendingEventsWithSources,
		updateEventStatus
	} from '$lib/services/events.js';
	import { createSenderRule } from '$lib/services/sender-rules.js';
	import { syncEventToCalendar } from '$lib/api/backend.js';
	import { initiateGmailAuth, initiateCalendarAuth, initiatePhotosAuth } from '$lib/api/backend.js';
	import IntegrationStatus from '$lib/components/IntegrationStatus.svelte';
	import SenderHeader from '$lib/components/SenderHeader.svelte';
	import EventCard from '$lib/components/EventCard.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import ErrorAlert from '$lib/components/ErrorAlert.svelte';
	import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';

	/** @type {any[]} */
	let integrationsList = $state([]);
	/** @type {any[]} */
	let events = $state([]);
	let isLoadingIntegrations = $state(true);
	let isLoadingEvents = $state(false);
	let error = $state('');
	let notification = $state('');

	let gmailIntegration = $derived(integrationsList.find((i) => i.provider === 'gmail'));
	let gcalIntegration = $derived(
		integrationsList.find((i) => i.provider === 'google_calendar')
	);
	let fullyConnected = $derived(
		gmailIntegration?.status === 'active' && gcalIntegration?.status === 'active'
	);

	// Group events by sender (flat — no email sub-grouping)
	let groupedEvents = $derived(() => {
		const senderMap = new Map();
		for (const event of events) {
			const sources = event.event_sources || [];
			const firstSource = sources[0];

			let senderKey;
			let senderName;

			if (firstSource?.source_origin === 'google_photos') {
				senderKey = 'google_photos';
				senderName = $_('integrations.googlePhotos');
			} else {
				const email = firstSource?.emails;
				senderKey = email?.from_email || $_('common.unknownSender');
				senderName = email?.from_name || senderKey;
			}

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
	});

	onMount(async () => {
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

		// If fully connected, load events
		if (
			integrationsList.find((i) => i.provider === 'gmail')?.status === 'active' &&
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
	async function handleApprove(event) {
		const { error: updateError } = await updateEventStatus(event.id, 'approved');
		if (updateError) {
			error = updateError.message;
			return;
		}
		events = events.filter((e) => e.id !== event.id);
		// Fire and forget calendar sync
		syncEventToCalendar(event.id);
	}

	/** @param {any} event */
	async function handleReject(event) {
		const { error: updateError } = await updateEventStatus(event.id, 'rejected');
		if (updateError) {
			error = updateError.message;
			return;
		}
		events = events.filter((e) => e.id !== event.id);
	}

	/** @param {any[]} eventsList */
	async function handleApproveAll(eventsList) {
		for (const event of eventsList) {
			await handleApprove(event);
		}
	}

	/** @param {any[]} eventsList */
	async function handleRejectAll(eventsList) {
		for (const event of eventsList) {
			await handleReject(event);
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
			await handleReject(event);
		}
		notification = $_('home.senderIgnored', { values: { senderEmail } });
		setTimeout(() => { notification = ''; }, 3000);
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
			await handleApprove(event);
		}
		notification = $_('home.senderAutoApproved', { values: { senderEmail } });
		setTimeout(() => { notification = ''; }, 3000);
	}

	function handleConnect() {
		initiateGmailAuth();
	}

	/** @param {string} provider */
	function handleAuthorize(provider) {
		if (provider === 'gmail') {
			initiateGmailAuth();
		} else if (provider === 'google_calendar') {
			initiateCalendarAuth();
		} else if (provider === 'google_photos') {
			initiatePhotosAuth();
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
	<div class="space-y-6">
		{#each [...groupedEvents().entries()] as [senderKey, senderGroup]}
			<div>
				<SenderHeader
					sender={senderGroup.senderName}
					senderEmail={senderKey}
					eventCount={senderGroup.events.length}
					onapproveAll={() => handleApproveAll(senderGroup.events)}
					onrejectAll={() => handleRejectAll(senderGroup.events)}
					onignoreSender={() => handleIgnoreSender(senderKey, senderGroup.events)}
					onautoApproveSender={() => handleAutoApproveSender(senderKey, senderGroup.events)}
				/>
				{#each senderGroup.events as event (event.id)}
					<EventCard
						{event}
						onapprove={handleApprove}
						onreject={handleReject}
					/>
				{/each}
			</div>
		{/each}
	</div>
{/if}
