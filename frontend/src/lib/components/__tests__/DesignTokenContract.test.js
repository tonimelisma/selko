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
		['dark CHANGED tag', 'dark', 'changedForeground', 'changedBackground', 4.5]
	])('%s meets contrast', (_name, mode, foreground, background, minimum) => {
		expect(contrast(tokens.color[mode][foreground], tokens.color[mode][background])).toBeGreaterThanOrEqual(minimum);
	});
});
