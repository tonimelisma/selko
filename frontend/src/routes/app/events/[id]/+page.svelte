<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { get } from 'svelte/store';
	import { _ } from 'svelte-i18n';
	import { getEvent, updateEvent, updateEventStatus } from '$lib/services/events.js';
	import { undoHistoryEvent } from '$lib/api/backend.js';
	import { fetchEventSources } from '$lib/services/event-sources.js';
	import { getEmail } from '$lib/services/emails.js';
	import { fetchAttachments } from '$lib/services/attachments.js';
	import { fetchIntegrations } from '$lib/services/integrations.js';
	import {
		initiateCalendarAuth,
		initiateGmailAuth,
		initiateOutlookAuth
	} from '$lib/api/backend.js';
import StatusBadge from '$lib/components/StatusBadge.svelte';
	import ConnectionRecovery from '$lib/components/ConnectionRecovery.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import ErrorAlert from '$lib/components/ErrorAlert.svelte';
	import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';

	let eventId = $state('');
	/** @type {any} */
	let event = $state(null);
	/** @type {any[]} */
	let sources = $state([]);
	/** @type {any} */
	let sourceEmail = $state(null);
	/** @type {any[]} */
	let attachments = $state([]);
	/** @type {string} */
	let sourceOrigin = $state('email');
	let isLoading = $state(true);
	let isSaving = $state(false);
	let isActing = $state(false);
	let error = $state('');
	let sourceExpanded = $state(false);
	/** @type {any[]} */
	let integrations = $state([]);
	let calendarConnected = $derived(
		integrations.some(
			(integration) =>
				integration.provider === 'google_calendar' && integration.status === 'active'
		)
	);
	/** @type {{event: any, timer: ReturnType<typeof setTimeout>} | null} */
	let rejectedUndo = $state(null);
	let undoingReject = $state(false);

	// Form fields
	let title = $state('');
	let allDay = $state(false);
	let eventDate = $state('');
	let startTime = $state('');
	let endTime = $state('');
	let location = $state('');
	let description = $state('');

	onMount(async () => {
		eventId = get(page).params.id || '';
		if (eventId) {
			await loadEventData();
		}
	});

		function clearRejectUndoTimer() {
		if (rejectedUndo?.timer) clearTimeout(rejectedUndo.timer);
	}

	function dismissRejectUndo() {
		clearRejectUndoTimer();
		rejectedUndo = null;
		goto('/app');
	}

	async function handleUndoRejected() {
		if (!rejectedUndo || undoingReject) return;
		const toRestore = rejectedUndo.event;
		clearRejectUndoTimer();
		rejectedUndo = null;
		undoingReject = true;
		const { error: undoError } = await undoHistoryEvent(toRestore.id);
		undoingReject = false;
		if (undoError) {
			error = undoError.message;
			return;
		}
		// Reload event to reflect restored pending_review status
		await loadEventData();
	}

	async function loadEventData() {
		isLoading = true;
		error = '';

		const [eventResult, sourcesResult, integrationsResult] = await Promise.all([
			getEvent(eventId),
			fetchEventSources(eventId),
			fetchIntegrations()
		]);

		if (eventResult.error) {
			error = eventResult.error.message;
			isLoading = false;
			return;
		}

		event = eventResult.data;
		sources = sourcesResult.data || [];
		integrations = integrationsResult.data || [];
		if (integrationsResult.error) {
			error = integrationsResult.error.message;
		}

		// Populate form fields
		if (event) {
			title = event.title || '';
			allDay = event.all_day || false;
			location = event.location || '';
			description = event.description || '';

			if (event.start_datetime) {
				const start = new Date(event.start_datetime);
				eventDate = start.toISOString().split('T')[0];
				startTime = start.toTimeString().slice(0, 5);
			}
			if (event.end_datetime) {
				const end = new Date(event.end_datetime);
				endTime = end.toTimeString().slice(0, 5);
			}
		}

		// Determine the source origin
		if (sources.length > 0) {
			sourceOrigin = sources[0].source_origin || 'email';
		}

		// Load source email if available (email sources only)
		if (sources.length > 0 && sources[0].email_id && sourceOrigin === 'email') {
			const emailId = sources[0].email_id;
			const [emailResult, attachResult] = await Promise.all([
				getEmail(emailId),
				fetchAttachments(emailId)
			]);
			sourceEmail = emailResult.data;
			attachments = attachResult.data || [];
		}

		isLoading = false;
	}

	async function handleSave() {
		if (!event) return;
		isSaving = true;

		/** @type {Record<string, any>} */
		const updates = {
			title,
			all_day: allDay,
			location: location || undefined,
			description: description || undefined
		};

		if (eventDate) {
			if (allDay) {
				updates.start_datetime = `${eventDate}T00:00:00Z`;
				if (endTime) {
					updates.end_datetime = `${eventDate}T23:59:59Z`;
				}
			} else {
				if (startTime) {
					updates.start_datetime = `${eventDate}T${startTime}:00Z`;
				}
				if (endTime) {
					updates.end_datetime = `${eventDate}T${endTime}:00Z`;
				}
			}
		}

		const result = await updateEvent(event.id, updates);
		if (result.error) {
			error = result.error.message;
		} else {
			event = result.data;
		}
		isSaving = false;
	}

	async function handleApprove() {
		if (!event || !title || isActing) return;
		if (!calendarConnected) {
			error = $_('integrations.calendarRequiredToAccept');
			return;
		}
		isActing = true;
		error = '';
		try {
			await handleSave();
			if (error) return;

			const { error: statusError } = await updateEventStatus(event.id, 'approved');
			if (statusError) {
				error = statusError.message;
				return;
			}
			goto('/app');
		} finally {
			isActing = false;
		}
	}

	/** @param {string} provider */
	async function handleAuthorize(provider) {
		if (provider === 'gmail') await initiateGmailAuth();
		if (provider === 'outlook') await initiateOutlookAuth();
		if (provider === 'google_calendar') await initiateCalendarAuth();
	}

	async function handleReject() {
		if (!event || isActing) return;
		isActing = true;
		error = '';
		try {
			const { error: statusError } = await updateEventStatus(event.id, 'rejected');
			if (statusError) {
				error = statusError.message;
				return;
			}
			const timer = setTimeout(() => {
				rejectedUndo = null;
				goto('/app');
			}, 8000);
			rejectedUndo = { event, timer };
		} finally {
			isActing = false;
		}
	}
</script>

{#if isLoading}
	<LoadingSpinner />
{:else if error && !event}
	<ErrorAlert message={error} onaction={() => goto('/app')} actionLabel={$_('events.backToReview')} />
{:else if event}
	<PageHeader title={$_('events.editEvent')} backHref="/app">
		{#snippet children()}
			<StatusBadge status={event.status} />
		{/snippet}
	</PageHeader>

	{#if error}
		<ErrorAlert message={error} />
	{/if}
	<ConnectionRecovery {integrations} onauthorize={handleAuthorize} />

	<div class="grid grid-cols-1 lg:grid-cols-5 gap-6">
		<!-- Source sidebar -->
		{#if sourceEmail}
			<div class="lg:col-span-2 order-1 lg:order-1">
				<!-- Desktop: always visible -->
				<div class="hidden lg:block">
					<div class="warm-card">
						<div class="card-body">
							<h3 class="card-title text-sm">{$_('eventSource.sourceEmail')}</h3>
							<div class="space-y-2 text-sm">
								<p><span class="font-medium">{$_('eventSource.from')}</span> {sourceEmail.from_name || sourceEmail.from_email}</p>
								<p><span class="font-medium">{$_('eventSource.subject')}</span> {sourceEmail.subject || $_('eventSource.noSubject')}</p>
								{#if sourceEmail.date_sent}
									<p><span class="font-medium">{$_('eventSource.date')}</span> {new Date(sourceEmail.date_sent).toLocaleDateString()}</p>
								{/if}
								{#if sourceEmail.snippet}
									<div class="mt-3 rounded-[14px] border border-base-300 bg-base-100 p-3 text-sm text-base-content/70">
										{sourceEmail.snippet}
									</div>
								{/if}
								{#if attachments.length > 0}
									<div class="mt-3">
										<p class="font-medium">{$_('eventSource.attachments', { values: { count: attachments.length } })}</p>
										<ul class="list-disc list-inside mt-1">
											{#each attachments as attachment}
												<li class="text-base-content/70">{attachment.filename}</li>
											{/each}
										</ul>
									</div>
								{/if}
							</div>
						</div>
					</div>
				</div>

				<!-- Mobile/Tablet: collapsible -->
				<div class="lg:hidden">
					<div class="collapse collapse-arrow warm-card">
						<input type="checkbox" bind:checked={sourceExpanded} />
						<div class="collapse-title font-medium">
							{$_('eventSource.viewSourceEmail')}
						</div>
						<div class="collapse-content">
							<div class="space-y-2 text-sm">
								<p><span class="font-medium">{$_('eventSource.from')}</span> {sourceEmail.from_name || sourceEmail.from_email}</p>
								<p><span class="font-medium">{$_('eventSource.subject')}</span> {sourceEmail.subject || $_('eventSource.noSubject')}</p>
								{#if sourceEmail.date_sent}
									<p><span class="font-medium">{$_('eventSource.date')}</span> {new Date(sourceEmail.date_sent).toLocaleDateString()}</p>
								{/if}
								{#if sourceEmail.snippet}
									<div class="mt-3 rounded-[14px] border border-base-300 bg-base-100 p-3 text-sm text-base-content/70">
										{sourceEmail.snippet}
									</div>
								{/if}
								{#if attachments.length > 0}
									<div class="mt-3">
										<p class="font-medium">{$_('eventSource.attachments', { values: { count: attachments.length } })}</p>
										<ul class="list-disc list-inside mt-1">
											{#each attachments as attachment}
												<li class="text-base-content/70">{attachment.filename}</li>
											{/each}
										</ul>
									</div>
								{/if}
							</div>
						</div>
					</div>
				</div>
			</div>
		{:else if sourceOrigin === 'google_photos'}
			<div class="lg:col-span-2 order-1 lg:order-1">
				<!-- Desktop: always visible -->
				<div class="hidden lg:block">
					<div class="warm-card">
						<div class="card-body">
							<h3 class="card-title text-sm">{$_('eventSource.sourcePhoto')}</h3>
							<div class="space-y-2 text-sm">
								<p class="text-base-content/70">{$_('eventSource.sourcePhotoDescription')}</p>
								{#if event.source_attribution}
									<div class="mt-3 rounded-[14px] border border-base-300 bg-base-100 p-3 text-sm text-base-content/70">
										{event.source_attribution}
									</div>
								{/if}
							</div>
						</div>
					</div>
				</div>

				<!-- Mobile/Tablet: collapsible -->
				<div class="lg:hidden">
					<div class="collapse collapse-arrow warm-card">
						<input type="checkbox" bind:checked={sourceExpanded} />
						<div class="collapse-title font-medium">
							{$_('eventSource.viewSourcePhoto')}
						</div>
						<div class="collapse-content">
							<div class="space-y-2 text-sm">
								<p class="text-base-content/70">{$_('eventSource.sourcePhotoDescription')}</p>
								{#if event.source_attribution}
									<div class="mt-3 rounded-[14px] border border-base-300 bg-base-100 p-3 text-sm text-base-content/70">
										{event.source_attribution}
									</div>
								{/if}
							</div>
						</div>
					</div>
				</div>
			</div>
		{/if}

		<!-- Event form -->
		<div class="{sourceEmail || sourceOrigin === 'google_photos' ? 'lg:col-span-3' : 'lg:col-span-5'} order-2 lg:order-2">
			<form onsubmit={(e) => { e.preventDefault(); handleSave(); }} class="space-y-4 pb-24 lg:pb-0">
				<div class="form-control">
					<label class="label" for="event-title">
						<span class="label-text">{$_('events.titleLabel')}</span>
					</label>
					<input
						id="event-title"
						type="text"
						bind:value={title}
						class="input input-bordered w-full bg-base-100"
						required
						onblur={handleSave}
					/>
				</div>

				<div class="form-control">
					<label class="label cursor-pointer justify-start gap-3" for="event-all-day">
						<input
							id="event-all-day"
							type="checkbox"
							bind:checked={allDay}
						class="checkbox checkbox-primary"
							onchange={handleSave}
						/>
						<span class="label-text">{$_('events.allDay')}</span>
					</label>
				</div>

				<div class="form-control">
					<label class="label" for="event-date">
						<span class="label-text">{$_('events.dateLabel')}</span>
					</label>
					<input
						id="event-date"
						type="date"
						bind:value={eventDate}
						class="input input-bordered w-full bg-base-100"
						required
						onblur={handleSave}
					/>
				</div>

				{#if !allDay}
					<div class="grid grid-cols-2 gap-4">
						<div class="form-control">
							<label class="label" for="event-start-time">
								<span class="label-text">{$_('events.startTime')}</span>
							</label>
							<input
								id="event-start-time"
								type="time"
								bind:value={startTime}
								class="input input-bordered w-full bg-base-100"
								required
								onblur={handleSave}
							/>
						</div>
						<div class="form-control">
							<label class="label" for="event-end-time">
								<span class="label-text">{$_('events.endTime')}</span>
							</label>
							<input
								id="event-end-time"
								type="time"
								bind:value={endTime}
								class="input input-bordered w-full bg-base-100"
								onblur={handleSave}
							/>
						</div>
					</div>
				{/if}

				<div class="form-control">
					<label class="label" for="event-location">
						<span class="label-text">{$_('events.locationLabel')}</span>
					</label>
					<input
						id="event-location"
						type="text"
						bind:value={location}
						class="input input-bordered w-full bg-base-100"
						placeholder={$_('events.locationPlaceholder')}
						onblur={handleSave}
					/>
				</div>

				<div class="form-control">
					<label class="label" for="event-description">
						<span class="label-text">{$_('events.descriptionLabel')}</span>
					</label>
					<textarea
						id="event-description"
						bind:value={description}
						class="textarea textarea-bordered w-full bg-base-100"
						rows="3"
						placeholder={$_('events.descriptionPlaceholder')}
						onblur={handleSave}
					></textarea>
				</div>
			</form>

			<!-- Desktop action buttons -->
			{#if event.status === 'pending_review'}
				<div class="peer-action-wrap mt-6 hidden lg:block">
					<div class="peer-action-group" data-peer-count="2">
						<button class="btn peer-action peer-action-destructive" onclick={handleReject} disabled={isActing} aria-label={`${$_('events.reject')} ${event.title}`} aria-busy={isActing}>
							{#if isActing}
								<span class="loading loading-spinner loading-sm" aria-hidden="true"></span>
							{:else}
								<svg xmlns="http://www.w3.org/2000/svg" class="peer-icon h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.3" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="m7 7 10 10M17 7 7 17" /></svg>
								{$_('events.reject')}
							{/if}
						</button>
						<button class="btn peer-action peer-action-accept" onclick={handleApprove} disabled={!title || isActing || !calendarConnected} aria-label={`${$_('events.accept')} ${event.title}${calendarConnected ? '' : `. ${$_('integrations.calendarRequiredToAccept')}`}`} aria-busy={isActing}>
							{#if isActing}
								<span class="loading loading-spinner loading-sm" aria-hidden="true"></span>
							{:else}
								<svg xmlns="http://www.w3.org/2000/svg" class="peer-icon h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.3" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="m5 12 4 4L19 6" /></svg>
								{$_('events.accept')}
							{/if}
						</button>
					</div>
				</div>
			{/if}
		</div>
	</div>

	{#if rejectedUndo}
		<div class="toast toast-bottom toast-center z-50" role="status" aria-live="polite">
			<div class="alert bg-base-100 shadow-lg border border-base-300 gap-3 max-w-md">
				<span class="text-sm font-medium">{$_('home.eventRejected')}</span>
				<button class="btn btn-sm btn-primary" disabled={undoingReject} onclick={handleUndoRejected}>
					{#if undoingReject}<span class="loading loading-spinner loading-xs"></span>{/if}
					{$_('history.undo')}
				</button>
				<button class="btn btn-ghost btn-sm btn-circle" onclick={dismissRejectUndo} aria-label={$_('common.dismiss')}>✕</button>
			</div>
		</div>
	{/if}
	<!-- Mobile fixed bottom action bar -->
	{#if event.status === 'pending_review'}
		<div class="fixed bottom-0 left-0 right-0 border-t border-base-300 bg-surface p-4 lg:hidden">
			<div class="peer-action-wrap mx-auto w-full max-w-[var(--review-max-width)]">
				<div class="peer-action-group" data-peer-count="2">
					<button class="btn peer-action peer-action-destructive" onclick={handleReject} disabled={isActing} aria-label={`${$_('events.reject')} ${event.title}`} aria-busy={isActing}>
						{#if isActing}
							<span class="loading loading-spinner loading-sm" aria-hidden="true"></span>
						{:else}
							<svg xmlns="http://www.w3.org/2000/svg" class="peer-icon h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.3" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="m7 7 10 10M17 7 7 17" /></svg>
							{$_('events.reject')}
						{/if}
					</button>
					<button class="btn peer-action peer-action-accept" onclick={handleApprove} disabled={!title || isActing || !calendarConnected} aria-label={`${$_('events.accept')} ${event.title}${calendarConnected ? '' : `. ${$_('integrations.calendarRequiredToAccept')}`}`} aria-busy={isActing}>
						{#if isActing}
							<span class="loading loading-spinner loading-sm" aria-hidden="true"></span>
						{:else}
							<svg xmlns="http://www.w3.org/2000/svg" class="peer-icon h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.3" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="m5 12 4 4L19 6" /></svg>
							{$_('events.accept')}
						{/if}
					</button>
				</div>
			</div>
		</div>
	{/if}
{/if}
