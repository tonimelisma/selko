<script>
	import { page } from '$app/stores';
	import { _ } from 'svelte-i18n';
	import { user } from '$lib/stores.js';
	import { initialsFromEmail } from '$lib/user-display.js';
	import LogoMark from './LogoMark.svelte';

	let { onLogout } = $props();

	let currentPath = $state('/app');
	let currentUserEmail = $state('');

	$effect(() => {
		const unsubscribePage = page.subscribe((value) => {
			currentPath = value.url.pathname;
		});
		const unsubscribeUser = user.subscribe((value) => {
			currentUserEmail = value?.email || '';
		});
		return () => {
			unsubscribePage();
			unsubscribeUser();
		};
	});

	let navLinks = $derived([
		{ href: '/app', label: $_('nav.review'), icon: 'review' },
		{ href: '/app/history', label: $_('nav.history'), icon: 'history' },
		{ href: '/app/settings', label: $_('nav.settings'), icon: 'settings' }
	]);

	let initials = $derived(initialsFromEmail(currentUserEmail));
</script>

<!-- Desktop sidebar (≥lg). CSS breakpoints, not JS, so SSR/first paint match. -->
<aside class="fixed inset-y-0 left-0 z-40 hidden w-[236px] flex-col border-r border-base-300 bg-surface px-4 py-5 lg:flex">
	<a href="/app" class="flex items-center gap-2 px-2" aria-label={$_('common.appName')}>
		<LogoMark size={34} />
		<span class="text-xl font-extrabold tracking-tight">{$_('common.appName')}</span>
	</a>

	<nav class="mt-10" aria-label={$_('nav.mainNavigation')}>
		<ul class="space-y-1">
			{#each navLinks as link}
				<li>
					<a
						href={link.href}
						class="flex items-center gap-3 rounded-xl px-3 py-3 text-sm font-semibold transition-colors {currentPath === link.href ? 'bg-base-200 text-secondary' : 'text-base-content/60 hover:bg-base-200 hover:text-base-content'}"
						aria-current={currentPath === link.href ? 'page' : undefined}
					>
						{#if link.icon === 'review'}
							<svg xmlns="http://www.w3.org/2000/svg" class="h-[18px] w-[18px]" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path stroke-linecap="round" d="M5 6h14M5 12h14M5 18h9" /></svg>
						{:else if link.icon === 'history'}
							<svg xmlns="http://www.w3.org/2000/svg" class="h-[18px] w-[18px]" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M12 7v5l3 2M20 12a8 8 0 1 1-2.34-5.66M20 5v4h-4" /></svg>
						{:else}
							<svg xmlns="http://www.w3.org/2000/svg" class="h-[18px] w-[18px]" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path stroke-linecap="round" d="M5 7h14M5 12h14M5 17h14" /><circle cx="9" cy="7" r="1.5" fill="currentColor" stroke="none" /><circle cx="15" cy="12" r="1.5" fill="currentColor" stroke="none" /><circle cx="11" cy="17" r="1.5" fill="currentColor" stroke="none" /></svg>
						{/if}
						<span>{link.label}</span>
					</a>
				</li>
			{/each}
		</ul>
	</nav>

	<div class="mt-auto flex items-center gap-3 rounded-xl border-t border-base-300 px-2 pt-4">
		<div class="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-primary text-xs font-bold text-primary-content">{initials}</div>
		<div class="min-w-0 flex-1">
			<p class="truncate text-sm font-semibold">{currentUserEmail || $_('auth.account')}</p>
			<p class="text-xs text-base-content/50">{$_('common.appName')}</p>
		</div>
		<button class="btn btn-square action-tertiary text-error" onclick={onLogout} aria-label={$_('auth.logOut')}>
			<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M14 8V6.5A2.5 2.5 0 0 0 11.5 4h-5A2.5 2.5 0 0 0 4 6.5v11A2.5 2.5 0 0 0 6.5 20h5a2.5 2.5 0 0 0 2.5-2.5V16M10 12h10m0 0-3-3m3 3-3 3" /></svg>
		</button>
	</div>
</aside>

<!-- Mobile header + pill tabs (<lg). Logout lives at the foot of Settings. -->
<header class="sticky top-0 z-40 border-b border-base-300 bg-surface lg:hidden">
	<div class="flex min-h-16 items-center justify-between px-4">
		<a href="/app" class="flex items-center gap-2" aria-label={$_('common.appName')}>
			<LogoMark size={32} />
			<span class="text-lg font-extrabold tracking-tight">{$_('common.appName')}</span>
		</a>
		<div class="grid h-9 w-9 place-items-center rounded-full bg-primary text-xs font-bold text-primary-content" aria-label={currentUserEmail}>{initials}</div>
	</div>
	<nav class="px-4 pb-3" aria-label={$_('nav.mainNavigation')}>
		<div class="grid grid-cols-3 gap-1 rounded-full bg-base-200 p-1">
			{#each navLinks as link}
				<a
					href={link.href}
					class="rounded-full px-2 py-2 text-center text-sm font-semibold transition-colors {currentPath === link.href ? 'bg-primary text-primary-content shadow-brand' : 'text-base-content/60 hover:text-base-content'}"
					aria-current={currentPath === link.href ? 'page' : undefined}
				>
					{link.label}
				</a>
			{/each}
		</div>
	</nav>
</header>
