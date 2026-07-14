<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { get } from 'svelte/store';
	import { _ } from 'svelte-i18n';
	import { getEvent, updateEvent, updateEventStatus } from '$lib/services/events.js';
	import { fetchEventSources } from '$lib/services/event-sources.js';
	import { getEmail } from '$lib/services/emails.js';
	import { fetchAttachments } from '$lib/services/attachments.js';
	import { syncEventToCalendar } from '$lib/api/backend.js';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
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

	async function loadEventData() {
		isLoading = true;
		error = '';

		const [eventResult, sourcesResult] = await Promise.all([
			getEvent(eventId),
			fetchEventSources(eventId)
		]);

		if (eventResult.error) {
			error = eventResult.error.message;
			isLoading = false;
			return;
		}

		event = eventResult.data;
		sources = sourcesResult.data || [];

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
			syncEventToCalendar(event.id);
			goto('/app');
		} finally {
			isActing = false;
		}
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
			goto('/app');
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
				<div class="hidden lg:flex justify-end gap-3 mt-6">
					<button class="btn btn-outline btn-error rounded-[11px]" onclick={handleReject} disabled={isActing}>
						{#if isActing}
							<span class="loading loading-spinner loading-sm"></span>
						{:else}
							{$_('events.reject')}
						{/if}
					</button>
					<button class="btn btn-success rounded-[11px]" onclick={handleApprove} disabled={!title || isActing}>
						{#if isActing}
							<span class="loading loading-spinner loading-sm"></span>
						{:else}
							{$_('events.accept')}
						{/if}
					</button>
				</div>
			{/if}
		</div>
	</div>

	<!-- Mobile fixed bottom action bar -->
	{#if event.status === 'pending_review'}
		<div class="fixed bottom-0 left-0 right-0 border-t border-base-300 bg-surface p-4 lg:hidden">
			<div class="flex justify-end gap-3 max-w-7xl mx-auto">
				<button class="btn btn-outline btn-error flex-1 rounded-[11px]" onclick={handleReject} disabled={isActing}>
					{#if isActing}
						<span class="loading loading-spinner loading-sm"></span>
					{:else}
						{$_('events.reject')}
					{/if}
				</button>
				<button class="btn btn-success flex-1 rounded-[11px]" onclick={handleApprove} disabled={!title || isActing}>
					{#if isActing}
						<span class="loading loading-spinner loading-sm"></span>
					{:else}
						{$_('events.accept')}
					{/if}
				</button>
			</div>
		</div>
	{/if}
{/if}
