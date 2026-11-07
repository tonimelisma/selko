<script>
	/**
	 * Apps the user let into their Selko account through the OAuth consent
	 * page (for example Claude). Disconnecting revokes the grant: Supabase
	 * deletes that app's sessions, so its tokens stop working within a minute
	 * (the MCP endpoint caches a validated token for at most 60 seconds).
	 */
	import { onMount } from 'svelte';
	import { _ } from 'svelte-i18n';
	import { supabase } from '$lib/supabase.js';
	import InlineActionError from '$lib/components/InlineActionError.svelte';

	/** @type {{ client: { id: string, name: string }, scopes: string[], granted_at: string }[]} */
	let grants = $state([]);
	let loaded = $state(false);
	let revoking = $state('');
	let error = $state('');

	async function load() {
		// The OAuth server may be disabled in some environments; then there is
		// nothing to list and the section stays hidden.
		try {
			const { data, error: listError } = await supabase.auth.oauth.listGrants();
			grants = listError ? [] : data ?? [];
		} catch {
			grants = [];
		}
		loaded = true;
	}

	/** @param {string} clientId */
	async function revoke(clientId) {
		revoking = clientId;
		error = '';
		const { error: revokeError } = await supabase.auth.oauth.revokeGrant({ clientId });
		revoking = '';
		if (revokeError) {
			error = $_('connectedApps.revokeFailed');
			return;
		}
		grants = grants.filter((grant) => grant.client.id !== clientId);
	}

	/** @param {string} iso */
	function since(iso) {
		return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
	}

	onMount(load);
</script>

{#if loaded && grants.length > 0}
	<section data-testid="connected-apps">
		<h2 class="mb-4 text-[11px] font-bold uppercase tracking-[0.08em] text-secondary">{$_('connectedApps.heading')}</h2>
		<div class="space-y-3">
			{#each grants as grant (grant.client.id)}
				<div class="warm-card flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
					<div>
						<p class="text-sm font-semibold">{grant.client.name}</p>
						<p class="mt-1 text-xs text-base-content/65">
							{$_('connectedApps.connectedSince', { values: { date: since(grant.granted_at) } })}
						</p>
					</div>
					<div class="peer-action-group min-w-56" data-peer-count="1">
						<button
							class="btn peer-action peer-action-destructive"
							disabled={revoking !== ''}
							aria-busy={revoking === grant.client.id}
							onclick={() => revoke(grant.client.id)}
						>
							{$_('connectedApps.disconnect', { values: { name: grant.client.name } })}
						</button>
					</div>
				</div>
			{/each}
			{#if error}
				<InlineActionError message={error} />
			{/if}
		</div>
	</section>
{/if}
