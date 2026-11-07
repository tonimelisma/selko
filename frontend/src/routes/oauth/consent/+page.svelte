<script>
	/**
	 * OAuth consent for apps that connect to Selko (e.g. Claude, via Selko's
	 * MCP endpoint). Supabase Auth's OAuth 2.1 server sends the browser here
	 * with ?authorization_id=…; approving or denying hands the browser back to
	 * the app's redirect URI. Apps register themselves (dynamic client
	 * registration), so this page is the only gate: it names the app, and
	 * nothing is shared until the user chooses Allow.
	 */
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { _ } from 'svelte-i18n';
	import { supabase } from '$lib/supabase.js';
	import ErrorAlert from '$lib/components/ErrorAlert.svelte';
	import LogoMark from '$lib/components/LogoMark.svelte';

	/** @type {'loading' | 'ready' | 'deciding' | 'redirecting' | 'error'} */
	let phase = $state('loading');
	let error = $state('');
	let authorizationId = $state('');
	let clientName = $state('');
	let email = $state('');
	let returnHost = $state('');

	onMount(async () => {
		const params = new URLSearchParams(window.location.search);
		authorizationId = params.get('authorization_id') || '';
		if (!authorizationId) {
			error = $_('oauthConsent.missingRequestGeneric');
			phase = 'error';
			return;
		}

		const { data: sessionData } = await supabase.auth.getSession();
		if (!sessionData?.session) {
			const here = window.location.pathname + window.location.search;
			goto(`/login?next=${encodeURIComponent(here)}`);
			return;
		}

		const { data, error: detailsError } = await supabase.auth.oauth.getAuthorizationDetails(authorizationId);
		if (detailsError || !data) {
			error = $_('oauthConsent.loadFailed');
			phase = 'error';
			return;
		}
		if (!('authorization_id' in data)) {
			// Already consented earlier: Supabase hands back the code directly.
			phase = 'redirecting';
			window.location.assign(data.redirect_url);
			return;
		}
		clientName = data.client?.name || 'This app';
		email = data.user?.email || sessionData.session.user?.email || '';
		// Apps name themselves when they register, so show where approving
		// actually sends the user: a fake "Claude" cannot fake this.
		try {
			returnHost = data.redirect_uri ? new URL(data.redirect_uri).host : '';
		} catch {
			returnHost = '';
		}
		phase = 'ready';
	});

	/** @param {boolean} approve */
	async function decide(approve) {
		phase = 'deciding';
		error = '';
		const call = approve
			? supabase.auth.oauth.approveAuthorization(authorizationId)
			: supabase.auth.oauth.denyAuthorization(authorizationId);
		// Both redirect the browser back to the app on success.
		const { data, error: decisionError } = await call;
		if (decisionError || !data?.redirect_url) {
			error = $_('oauthConsent.decisionFailed');
			phase = 'ready';
			return;
		}
		phase = 'redirecting';
	}
</script>

<svelte:head>
	<title>{$_('oauthConsent.title', { values: { client: clientName || 'app' } })}</title>
</svelte:head>

<main id="main-content" class="flex min-h-screen items-center justify-center bg-base-100 px-4 py-10">
	<div class="warm-card w-full max-w-md">
		<div class="card-body gap-4">
			<div class="flex flex-col items-center text-center">
				<LogoMark size={44} />
				{#if phase === 'ready' || phase === 'deciding' || phase === 'redirecting'}
					<h1 class="mt-4 text-2xl font-extrabold tracking-tight">
						{$_('oauthConsent.heading', { values: { client: clientName } })}
					</h1>
					{#if email}
						<p class="mt-1 text-sm text-base-content/60" data-testid="consent-account">
							{$_('oauthConsent.signedInAs', { values: { email } })}
						</p>
					{/if}
				{/if}
			</div>

			{#if phase === 'loading'}
				<div class="flex justify-center py-6" role="status">
					<span class="loading loading-spinner loading-md" aria-hidden="true"></span>
					<span class="sr-only">{$_('common.loading')}</span>
				</div>
			{:else if phase === 'error'}
				<ErrorAlert message={error} />
			{:else if phase === 'redirecting'}
				<p class="py-4 text-center text-sm text-base-content/70" role="status">
					{$_('oauthConsent.redirecting', { values: { client: clientName || 'the app' } })}
				</p>
			{:else}
				{#if error}
					<ErrorAlert message={error} />
				{/if}
				<div>
					<h2 class="text-sm font-semibold">
						{$_('oauthConsent.canHeading', { values: { client: clientName } })}
					</h2>
					<ul class="mt-2 list-disc space-y-1 pl-5 text-sm text-base-content/80">
						<li>{$_('oauthConsent.canSee')}</li>
						<li>{$_('oauthConsent.canDecide')}</li>
						<li>{$_('oauthConsent.canSync')}</li>
					</ul>
					<p class="mt-3 text-sm text-base-content/70">{$_('oauthConsent.cannot')}</p>
					{#if returnHost}
						<p class="mt-3 text-xs text-base-content/60" data-testid="consent-return-host">
							{$_('oauthConsent.returnsTo', { values: { host: returnHost } })}
						</p>
					{/if}
					<p class="mt-1 text-xs text-base-content/60">{$_('oauthConsent.revokeHint')}</p>
				</div>
				<div class="flex flex-col-reverse gap-2 sm:flex-row">
					<button
						type="button"
						class="btn btn-ghost min-h-11 flex-1 rounded-[14px]"
						onclick={() => decide(false)}
						disabled={phase === 'deciding'}
					>
						{$_('oauthConsent.cancel')}
					</button>
					<button
						type="button"
						class="btn btn-primary min-h-11 flex-1 rounded-[14px] shadow-brand"
						onclick={() => decide(true)}
						disabled={phase === 'deciding'}
						aria-busy={phase === 'deciding'}
					>
						{$_('oauthConsent.allow')}
					</button>
				</div>
			{/if}
		</div>
	</div>
</main>
