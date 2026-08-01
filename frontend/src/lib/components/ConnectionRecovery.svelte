<script>
	import { _ } from 'svelte-i18n';
	import ErrorAlert from './ErrorAlert.svelte';

	let { integrations = [], onauthorize } = $props();
	let connectingProvider = $state('');
	let connectError = $state('');

	let gmail = $derived(integrations.find((item) => item.provider === 'gmail'));
	let outlook = $derived(integrations.find((item) => item.provider === 'outlook'));
	let calendar = $derived(integrations.find((item) => item.provider === 'google_calendar'));
	let emailConnected = $derived(gmail?.status === 'active' || outlook?.status === 'active');
	let calendarConnected = $derived(calendar?.status === 'active');

	let recoveryProviders = $derived.by(() => {
		if (!emailConnected) {
			return ['gmail', 'outlook', ...(!calendarConnected ? ['google_calendar'] : [])];
		}
		if (!calendarConnected) {
			return [
				'google_calendar',
				...(gmail && gmail.status !== 'active' ? ['gmail'] : []),
				...(outlook && outlook.status !== 'active' ? ['outlook'] : [])
			];
		}
		return integrations
			.filter(
				(item) => item.provider !== 'google_photos' && item.status !== 'active'
			)
			.map((item) => item.provider);
	});

	let title = $derived(
		!emailConnected
			? $_('integrations.reconnectEmailTitle')
			: !calendarConnected
				? $_('integrations.reconnectCalendarTitle')
				: $_('integrations.connectionAttentionTitle')
	);
	let description = $derived(
		!emailConnected
			? $_('integrations.reconnectEmailDescription')
			: !calendarConnected
				? $_('integrations.reconnectCalendarDescription')
				: $_('integrations.connectionAttentionDescription')
	);

	/** @param {string} provider */
	function providerName(provider) {
		if (provider === 'gmail') return $_('integrations.gmail');
		if (provider === 'outlook') return $_('integrations.outlook');
		return $_('integrations.googleCalendar');
	}

	/** @param {string} provider */
	function actionLabel(provider) {
		const integration = integrations.find((item) => item.provider === provider);
		const verb = integration ? $_('integrations.reconnect') : $_('integrations.connect');
		return `${verb} ${providerName(provider)}`;
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

{#if recoveryProviders.length > 0}
	<section class="warm-card mb-6 border border-warning/30 bg-warning/5 p-5" aria-labelledby="connection-recovery-title">
		{#if connectError}
			<div class="mb-4"><ErrorAlert message={connectError} /></div>
		{/if}
		<div class="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
			<div class="flex min-w-0 gap-3">
				<div class="grid h-11 w-11 shrink-0 place-items-center rounded-[12px] bg-base-200 text-warning" aria-hidden="true">
					<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8">
						<path stroke-linecap="round" stroke-linejoin="round" d="M8 12h8m-4-4v8M5.5 18.5a9 9 0 1 1 13 0" />
					</svg>
				</div>
				<div>
					<h2 id="connection-recovery-title" class="font-bold">{title}</h2>
					<p class="mt-1 max-w-2xl text-sm text-base-content/65">{description}</p>
				</div>
			</div>
			<div class="flex shrink-0 flex-wrap gap-2 sm:justify-end">
				<div class="peer-action-group" data-peer-count={Math.min(recoveryProviders.length, 3)}>
					{#each recoveryProviders as provider}
						<button
							class="btn btn-primary peer-action shadow-brand"
							disabled={connectingProvider !== ''}
							aria-busy={connectingProvider === provider}
							onclick={() => reconnect(provider)}
						>
							{#if connectingProvider === provider}
								<span class="loading loading-spinner loading-sm" aria-hidden="true"></span>
								{$_('integrations.connecting')}
							{:else}
								{actionLabel(provider)}
							{/if}
						</button>
					{/each}
				</div>
				<a class="btn action-secondary" href="/app/settings">{$_('integrations.manageConnections')}</a>
			</div>
		</div>
	</section>
{/if}
