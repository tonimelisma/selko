<script>
	import { onMount } from 'svelte';
	import { fetchIntegrations } from '$lib/services/integrations.js';
	import {
		fetchPendingEventsWithSources,
		updateEventStatus
	} from '$lib/services/events.js';
	import { syncEventToCalendar } from '$lib/api/backend.js';
	import { initiateGmailAuth, initiateCalendarAuth } from '$lib/api/backend.js';
	import IntegrationStatus from '$lib/components/IntegrationStatus.svelte';
	import SenderHeader from '$lib/components/SenderHeader.svelte';
	import EmailHeader from '$lib/components/EmailHeader.svelte';
	import EventCard from '$lib/components/EventCard.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';

	/** @type {any[]} */
	let integrationsList = $state([]);
	/** @type {any[]} */
	let events = $state([]);
	let isLoadingIntegrations = $state(true);
	let isLoadingEvents = $state(false);
	let error = $state('');

	let gmailIntegration = $derived(integrationsList.find((i) => i.provider === 'gmail'));
	let gcalIntegration = $derived(
		integrationsList.find((i) => i.provider === 'google_calendar')
	);
	let fullyConnected = $derived(
		gmailIntegration?.status === 'active' && gcalIntegration?.status === 'active'
	);

	// Group events by sender, then by email
	let groupedEvents = $derived(() => {
		const senderMap = new Map();
		for (const event of events) {
			const sources = event.event_sources || [];
			const firstSource = sources[0];
			const email = firstSource?.emails;
			const senderKey = email?.from_email || 'Unknown Sender';
			const emailKey = email?.id || 'unknown';

			if (!senderMap.has(senderKey)) {
				senderMap.set(senderKey, {
					sender: senderKey,
					senderName: email?.from_name || senderKey,
					emails: new Map()
				});
			}

			const senderGroup = senderMap.get(senderKey);
			if (!senderGroup.emails.has(emailKey)) {
				senderGroup.emails.set(emailKey, {
					email,
					events: []
				});
			}
			senderGroup.emails.get(emailKey).events.push(event);
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

	function handleConnect() {
		initiateGmailAuth();
	}

	/** @param {string} provider */
	function handleAuthorize(provider) {
		if (provider === 'gmail') {
			initiateGmailAuth();
		} else if (provider === 'google_calendar') {
			initiateCalendarAuth();
		}
	}
</script>

{#if isLoadingIntegrations}
	<div class="flex items-center justify-center py-16">
		<span class="loading loading-spinner loading-lg"></span>
	</div>
{:else if !fullyConnected}
	<IntegrationStatus
		integrations={integrationsList}
		setupMode={true}
		onconnect={handleConnect}
		onauthorize={handleAuthorize}
	/>
{:else if isLoadingEvents}
	<div class="space-y-4">
		<div class="h-8 bg-base-200 rounded animate-pulse w-48"></div>
		<div class="h-24 bg-base-200 rounded animate-pulse"></div>
		<div class="h-24 bg-base-200 rounded animate-pulse"></div>
		<div class="h-24 bg-base-200 rounded animate-pulse"></div>
	</div>
{:else if error}
	<div class="alert alert-error mb-4">
		<span>{error}</span>
		<button class="btn btn-sm btn-ghost" onclick={loadEvents}>Retry</button>
	</div>
{:else if events.length === 0}
	<EmptyState heading="All caught up!" description="No events pending review. Check back later for new events from your emails." />
{:else}
	<div class="space-y-6">
		{#each [...groupedEvents().entries()] as [senderKey, senderGroup]}
			<div>
				<SenderHeader
					sender={senderGroup.senderName}
					eventCount={[...senderGroup.emails.values()].reduce(
						(acc, eg) => acc + eg.events.length,
						0
					)}
					onapproveAll={() =>
						handleApproveAll(
							[...senderGroup.emails.values()].flatMap((eg) => eg.events)
						)}
				/>
				{#each [...senderGroup.emails.entries()] as [emailKey, emailGroup]}
					<EmailHeader
						subject={emailGroup.email?.subject || ''}
						date={emailGroup.email?.date_sent || ''}
						eventCount={emailGroup.events.length}
						onapproveAll={() => handleApproveAll(emailGroup.events)}
					/>
					{#each emailGroup.events as event (event.id)}
						<EventCard
							{event}
							onapprove={handleApprove}
							onreject={handleReject}
						/>
					{/each}
				{/each}
			</div>
		{/each}
	</div>
{/if}
