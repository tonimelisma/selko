<script>
	import { onMount } from 'svelte';
	import { _ } from 'svelte-i18n';
	import { fetchCalendarRecovery } from '$lib/services/integrations.js';
	import { recoveryPlan } from '$lib/calendar-providers.js';
	import ErrorAlert from './ErrorAlert.svelte';

	let { integrations = [], onauthorize } = $props();
	let connectingProvider = $state('');
	let connectError = $state('');

	/** @type {import('$lib/types.js').IntegrationRecovery | null} */
	let recovery = $state(null);
	/** @type {ReturnType<typeof setTimeout> | undefined} */
	let pollTimer = $state(undefined);
	let justCaughtUp = $state(false);

	// Names the account that stopped working and offers the one sign-in that
	// fixes it; see recoveryPlan.
	let plan = $derived(recoveryPlan(integrations));

	let title = $derived(plan ? $_(`integrations.recovery.${plan.kind}Title`) : '');
	let description = $derived.by(() => {
		if (!plan) return '';
		if (plan.kind === 'google' || plan.kind === 'outlook') {
			const lost = plan.lost === 'mailAndCalendar' ? 'MailAndCalendar' : plan.lost === 'mail' ? 'Mail' : 'Calendar';
			return $_(`integrations.recovery.${plan.kind}${lost}`);
		}
		return $_(`integrations.recovery.${plan.kind}`);
	});

	/** @param {import('$lib/types.js').IntegrationRecovery} r */
	function isTerminal(r) {
		return ['completed', 'completed_with_errors', 'failed', 'superseded'].includes(r.status);
	}

	/**
	 * @param {import('$lib/types.js').IntegrationRecovery | null} r
	 * @returns {'none' | 'starting' | 'catchingUp' | 'caughtUp' | 'withErrors' | 'failed'}
	 */
	function recoveryState(r) {
		if (!r) return 'none';
		if (r.status === 'pending' || r.status === 'processing') return 'starting';
		if (r.status === 'waiting') return 'catchingUp';
		if (r.status === 'completed') return justCaughtUp ? 'caughtUp' : 'none';
		if (r.status === 'completed_with_errors') return 'withErrors';
		if (r.status === 'failed') return 'failed';
		return 'none'; // superseded
	}

	let catchUpState = $derived(recoveryState(recovery));
	let showCatchUp = $derived(['starting', 'catchingUp', 'caughtUp', 'withErrors', 'failed'].includes(catchUpState));
	let catchUpNeedingAttention = $derived.by(() => {
		const r = /** @type {import('$lib/types.js').IntegrationRecovery | null} */ (recovery);
		if (!r) return 0;
		// 7a: remaining_count is authoritative (withdrawn events no longer undercount it);
		// fallback to discovered - completed - withdrawn for older rows lacking withdrawn_count.
		if (typeof r.remaining_count === 'number') return Math.max(0, r.remaining_count);
		return Math.max(0, (r.discovered_count ?? 0) - (r.completed_count ?? 0) - (r.withdrawn_count ?? 0));
	});

	async function loadRecovery() {
		// 7c: fetchCalendarRecovery never throws — it returns {data: null, error}. A single
		// network blip must not nuke the card (previous bug: recovery became null and the
		// self-rescheduling chain stopped). Keep previous value and retry with backoff.
		let data = null;
		let error = null;
		try {
			const result = await fetchCalendarRecovery();
			data = result.data;
			error = result.error;
		} catch (e) {
			error = e;
		}

		if (error) {
			// Keep previous recovery, retry soon. Do not null the card.
			pollTimer = setTimeout(loadRecovery, 5000);
			return;
		}

		const previous = recovery;
		recovery = data ?? previous ?? null;
		if (previous && previous.status !== 'completed' && data && data.status === 'completed') {
			justCaughtUp = true;
			setTimeout(() => {
				justCaughtUp = false;
			}, 4000);
		}
		if (data && !isTerminal(data)) {
			pollTimer = setTimeout(loadRecovery, 5000);
		} else if (!data && previous && !isTerminal(previous)) {
			// If data is null but previous was non-terminal (e.g. transient null), keep polling
			pollTimer = setTimeout(loadRecovery, 5000);
		}
	}

	// R7: keep 5s poll as debt with expiry — see live-ui-updates.md Broadcast
	// TODO(R7): replace with private per-user Broadcast on user:<uid>:selko-changes filtered resource=integration_recoveries; poll stays only as reconnect catch-up
	onMount(() => {
		loadRecovery();
		return () => {
			if (pollTimer) clearTimeout(pollTimer);
		};
	});

	/** @param {import('$lib/calendar-providers.js').RecoveryAction} action */
	function actionLabel(action) {
		const provider = action.provider === 'outlook' ? 'Outlook' : 'Google';
		return $_(`integrations.recovery.${action.verb}${provider}`);
	}

	/** @param {string} provider */
	async function reconnect(provider) {
		if (connectingProvider) return;
		connectingProvider = provider;
		connectError = '';
		try {
			await onauthorize?.(provider);
		} catch (error) {
			connectError =
				error instanceof Error && error.message
					? error.message
					: $_('integrations.connectFailed');
			connectingProvider = '';
		}
	}
</script>

{#if showCatchUp}
	<section class="warm-card mb-6 border border-warning/30 bg-warning/5 p-5" aria-labelledby="catch-up-title">
		<div class="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
			<div class="flex min-w-0 gap-3">
				<div class="grid h-11 w-11 shrink-0 place-items-center rounded-[12px] bg-base-200 text-warning" aria-hidden="true">
					{#if catchUpState === 'caughtUp'}
						<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8"><path stroke-linecap="round" stroke-linejoin="round" d="m5 13 4 4L19 7" /></svg>
					{:else}
						<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 animate-spin" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8"><path stroke-linecap="round" stroke-linejoin="round" d="M16 8a4 4 0 1 0-4 4 3 3 0 1 1-3 3" /></svg>
					{/if}
				</div>
				<div>
					<h2 id="catch-up-title" class="font-bold">
						{#if catchUpState === 'starting'}
							{$_('integrations.catchUpStarting')}
						{:else if catchUpState === 'catchingUp'}
							{$_('integrations.catchUpRemaining', { values: { count: recovery?.remaining_count ?? 0 } })}
						{:else if catchUpState === 'caughtUp'}
							{$_('integrations.catchUpCompleted')}
						{:else if catchUpState === 'withErrors'}
							{$_('integrations.catchUpCompletedWithErrors', { values: { count: catchUpNeedingAttention } })}
						{:else}
							{$_('integrations.catchUpFailed')}
						{/if}
					</h2>
					<p class="mt-1 max-w-2xl text-sm text-base-content/65">
						{#if catchUpState === 'starting'}
							{$_('integrations.catchUpStartingDescription')}
						{:else if catchUpState === 'catchingUp'}
							{$_('integrations.catchUpRemainingDescription')}
						{:else if catchUpState === 'caughtUp'}
							{$_('integrations.catchUpCompletedDescription')}
						{:else if catchUpState === 'withErrors'}
							{$_('integrations.catchUpCompletedWithErrorsDescription', { values: { count: catchUpNeedingAttention } })}
						{:else}
							{$_('integrations.catchUpFailedDescription')}
						{/if}
					</p>
				</div>
			</div>
			<a class="btn action-secondary shrink-0" href="/app/settings">{$_('integrations.manageConnections')}</a>
		</div>
	</section>
{/if}

{#if plan}
	<section class="warm-card mb-6 border border-warning/30 bg-warning/5 p-5" aria-labelledby="connection-recovery-title">
		{#if connectError}
			<div class="mb-4"><ErrorAlert message={connectError} /></div>
		{/if}
		<div class="flex min-w-0 gap-3">
			<div class="grid h-11 w-11 shrink-0 place-items-center rounded-[12px] bg-base-200 text-warning" aria-hidden="true">
				<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8">
					<path stroke-linecap="round" stroke-linejoin="round" d="M12 9v4m0 4h.01M10.3 3.9 2.4 17.5A2 2 0 0 0 4.1 20.5h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" />
				</svg>
			</div>
			<div class="min-w-0 flex-1">
				<h2 id="connection-recovery-title" class="font-bold">{title}</h2>
				<p class="mt-1 max-w-2xl text-sm text-base-content/65">{description}</p>
				<div class="mt-4 flex flex-wrap items-center gap-2">
					<div class="peer-action-group peer-action-group--intrinsic" data-peer-count={plan.actions.length}>
						{#each plan.actions as action (action.provider)}
							<button
								class="btn btn-primary peer-action"
								disabled={connectingProvider !== ''}
								aria-busy={connectingProvider === action.provider}
								onclick={() => reconnect(action.provider)}
							>
								{#if connectingProvider === action.provider}
									<span class="loading loading-spinner loading-sm" aria-hidden="true"></span>
									{$_('integrations.connecting')}
								{:else}
									{actionLabel(action)}
								{/if}
							</button>
						{/each}
					</div>
					<a class="btn action-tertiary" href="/app/settings">{$_('integrations.manageConnections')}</a>
				</div>
			</div>
		</div>
	</section>
{/if}
