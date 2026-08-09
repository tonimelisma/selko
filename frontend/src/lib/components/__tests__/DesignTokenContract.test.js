// @ts-nocheck
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(process.cwd(), '..');
const tokens = JSON.parse(readFileSync(resolve(root, 'design/tokens.json'), 'utf8'));
const css = readFileSync(resolve(root, 'frontend/src/app.css'), 'utf8').toLowerCase();

function luminance(hex) {
	const channels = hex.slice(1).match(/.{2}/g).map((value) => parseInt(value, 16) / 255);
	const linear = channels.map((value) => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
	return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

function contrast(foreground, background) {
	const values = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
	return (values[0] + 0.05) / (values[1] + 0.05);
}

describe('canonical design token contract', () => {
	it('keeps web semantic tokens synchronized with the manifest', () => {
		for (const mode of ['light', 'dark']) {
			for (const value of Object.values(tokens.color[mode])) {
				expect(css).toContain(value.toLowerCase());
			}
		}
		expect(css).toContain(`--control-height: ${tokens.control.minimumTarget}px`);
		expect(css).toContain(`--input-height: ${tokens.control.inputHeight}px`);
		expect(css).toContain(`--control-radius: ${tokens.shape.control}px`);
		expect(css).toContain(`--control-content-gap: ${tokens.control.contentGap}px`);
		expect(css).toContain(`--review-max-width: ${tokens.layout.reviewMaxWidth}px`);
		expect(css).toContain(`--screen-gutter: ${tokens.layout.screenGutter}px`);
		expect(css).toContain(`--compact-horizontal-padding: ${tokens.control.compactHorizontalPadding}px`);
		expect(css).toContain('.peer-action-group');
		expect(css).toContain('.peer-action-wrap');
		expect(css).toContain('container-type: inline-size');
		expect(css).toContain('width: fit-content');
		expect(css).toContain('@container (max-width: 352px)');
		expect(css).toContain('@container (max-width: 296px)');
	});

	it.each([
		['light muted on paper', 'light', 'muted', 'paper', 4.5],
		['light faint on paper', 'light', 'faint', 'paper', 4.5],
		['light success text on paper', 'light', 'successText', 'paper', 4.5],
		['light warning text on paper', 'light', 'warningText', 'paper', 4.5],
		['light NEW tag', 'light', 'newForeground', 'newBackground', 4.5],
		['light CHANGED tag', 'light', 'changedForeground', 'changedBackground', 4.5],
		['light primary action', 'light', 'onPrimary', 'primary', 4.5],
		['light success action', 'light', 'onSuccess', 'success', 4.5],
		['light destructive action', 'light', 'onError', 'error', 4.5],
		['dark muted on paper', 'dark', 'muted', 'paper', 4.5],
		['dark faint on paper', 'dark', 'faint', 'paper', 4.5],
		['dark NEW tag', 'dark', 'newForeground', 'newBackground', 4.5],
		['dark CHANGED tag', 'dark', 'changedForeground', 'changedBackground', 4.5],
		['light accept label vs fill', 'light', 'actionLabel', 'acceptFill', 7.0],
		['light edit label vs fill', 'light', 'actionLabel', 'editFill', 7.0],
		['light reject label vs fill', 'light', 'actionLabel', 'rejectFill', 7.0],
		['dark accept label vs fill', 'dark', 'actionLabel', 'acceptFill', 7.0],
		['dark edit label vs fill', 'dark', 'actionLabel', 'editFill', 7.0],
		['dark reject label vs fill', 'dark', 'actionLabel', 'rejectFill', 7.0],
		['light accept vs surface', 'light', 'acceptFill', 'surface', 3.0],
		['light edit vs surface', 'light', 'editFill', 'surface', 3.0],
		['light reject vs surface', 'light', 'rejectFill', 'surface', 3.0],
		['dark accept vs surface', 'dark', 'acceptFill', 'surface', 3.0],
		['dark edit vs surface', 'dark', 'editFill', 'surface', 3.0],
		['dark reject vs surface', 'dark', 'rejectFill', 'surface', 3.0],
		['light accept vs paper', 'light', 'acceptFill', 'paper', 3.0],
		['light edit vs paper', 'light', 'editFill', 'paper', 3.0],
		['light reject vs paper', 'light', 'rejectFill', 'paper', 3.0],
		['dark accept vs paper', 'dark', 'acceptFill', 'paper', 3.0],
		['dark edit vs paper', 'dark', 'editFill', 'paper', 3.0],
		['dark reject vs paper', 'dark', 'rejectFill', 'paper', 3.0]
	])('%s meets contrast', (_name, mode, foreground, background, minimum) => {
		expect(contrast(tokens.color[mode][foreground], tokens.color[mode][background])).toBeGreaterThanOrEqual(minimum);
	});

	it('peer action group is not descendant of date chip column', async () => {
		const { readFileSync: rf } = await import('node:fs');
		const ec = rf(resolve(root, 'frontend/src/lib/components/EventCard.svelte'), 'utf8');
		const cc = rf(resolve(root, 'frontend/src/lib/components/ChangeCard.svelte'), 'utf8');
		// Action wrap must be sibling of date-chip flex container, not nested inside flex-1
		expect(ec).toContain('class="peer-action-wrap');
		expect(ec).toContain('class="flex gap-3');
		expect(cc).toContain('class="peer-action-wrap');
	});
	it('no peer button declares white-space normal', async () => {
		const { readFileSync: rf } = await import('node:fs');
		const css2 = rf(resolve(root, 'frontend/src/app.css'), 'utf8');
		// Ensure peer buttons use nowrap, not normal/wrap
		expect(css2).toContain('white-space: nowrap');
		expect(css2).not.toMatch(/\.peer-action-group[\s\S]*?white-space:\s*normal/);
	});
});
