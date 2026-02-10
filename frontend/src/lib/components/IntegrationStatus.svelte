<script>
	import StatusBadge from './StatusBadge.svelte';

	let {
		integrations = [],
		setupMode = false,
		onconnect = undefined,
		ondisconnect = undefined,
		onauthorize = undefined
	} = $props();

	let gmailIntegration = $derived(integrations.find((i) => i.provider === 'gmail'));
	let gcalIntegration = $derived(integrations.find((i) => i.provider === 'google_calendar'));

	let gmailConnected = $derived(gmailIntegration?.status === 'active');
	let gcalConnected = $derived(gcalIntegration?.status === 'active');
	let fullyConnected = $derived(gmailConnected && gcalConnected);
	let partiallyConnected = $derived(gmailConnected || gcalConnected);

	const services = [
		{ key: 'gmail', label: 'Gmail', description: 'Read emails to find calendar events' },
		{
			key: 'google_calendar',
			label: 'Google Calendar',
			description: 'Sync approved events to your calendar'
		}
	];

	/** @param {string} key */
	function getIntegrationForService(key) {
		return integrations.find((i) => i.provider === key);
	}
</script>

{#if setupMode && !partiallyConnected}
	<div class="flex flex-col items-center justify-center py-16 px-4 text-center">
		<h2 class="text-2xl font-bold mb-2">Welcome to Selko</h2>
		<p class="text-base-content/70 max-w-md mb-6">
			Connect your Google account to get started. Selko will read your emails to find calendar
			events and sync them to your Google Calendar.
		</p>
		<button class="btn btn-primary" onclick={onconnect}>Connect Google Account</button>
	</div>
{:else}
	<div class="space-y-4">
		{#if setupMode}
			<h2 class="text-xl font-bold mb-4">Connect your accounts</h2>
		{/if}
		{#each services as service}
			{@const integration = getIntegrationForService(service.key)}
			<div class="flex items-center justify-between p-4 bg-base-200 rounded-lg">
				<div>
					<h3 class="font-semibold">{service.label}</h3>
					<p class="text-sm text-base-content/70">{service.description}</p>
					{#if integration?.provider_email}
						<p class="text-sm text-base-content/50 mt-1">{integration.provider_email}</p>
					{/if}
				</div>
				<div class="flex items-center gap-3">
					{#if integration}
						<StatusBadge status={integration.status} type="integration" />
						{#if !setupMode}
							<button
								class="btn btn-ghost btn-sm"
								onclick={() => ondisconnect?.(integration.id)}
							>
								Disconnect
							</button>
						{/if}
						{#if integration.status !== 'active'}
							<button
								class="btn btn-primary btn-sm"
								onclick={() => onauthorize?.(service.key)}
							>
								Reconnect
							</button>
						{/if}
					{:else}
						<StatusBadge status="not_connected" type="integration" />
						<button
							class="btn btn-primary btn-sm"
							onclick={() => onauthorize?.(service.key)}
						>
							Connect
						</button>
					{/if}
				</div>
			</div>
		{/each}
	</div>
{/if}
