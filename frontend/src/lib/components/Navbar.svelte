<script>
	import { page } from '$app/stores';

	let { onLogout } = $props();

	let currentPath = $state('/app');

	$effect(() => {
		const unsub = page.subscribe((p) => {
			currentPath = p.url.pathname;
		});
		return unsub;
	});

	const navLinks = [
		{ href: '/app', label: 'Review' },
		{ href: '/app/history', label: 'History' },
		{ href: '/app/settings', label: 'Settings' }
	];
</script>

<nav class="navbar bg-base-200" aria-label="Main navigation">
	<div class="navbar-start">
		<a href="/app" class="text-xl font-bold px-4">Selko</a>
	</div>
	<div class="navbar-center hidden lg:flex">
		<ul class="menu menu-horizontal px-1">
			{#each navLinks as link}
				<li>
					<a
						href={link.href}
						class={currentPath === link.href ? 'active' : ''}
						aria-current={currentPath === link.href ? 'page' : undefined}
					>
						{link.label}
					</a>
				</li>
			{/each}
		</ul>
	</div>
	<div class="navbar-end hidden lg:flex">
		<button class="btn btn-ghost" onclick={onLogout}>Log out</button>
	</div>
</nav>
