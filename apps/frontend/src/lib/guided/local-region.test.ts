import { describe, expect, it } from 'vitest';
import {
	REGION_STORAGE_KEY,
	readLocalRegionPreference,
	writeProvidedRegionPreference,
	writeRefusedRegionPreference,
} from './local-region.js';

class MemoryStorage implements Storage {
	private values = new Map<string, string>();

	get length(): number {
		return this.values.size;
	}

	clear(): void {
		this.values.clear();
	}

	getItem(key: string): string | null {
		return this.values.get(key) ?? null;
	}

	key(index: number): string | null {
		return Array.from(this.values.keys())[index] ?? null;
	}

	removeItem(key: string): void {
		this.values.delete(key);
	}

	setItem(key: string, value: string): void {
		this.values.set(key, value);
	}
}

describe('local region preference', () => {
	it('stores and reads a provided region', () => {
		const storage = new MemoryStorage();

		const saved = writeProvidedRegionPreference(storage, 'CA');
		const loaded = readLocalRegionPreference(storage);

		expect(saved).toEqual({
			status: 'provided',
			region: { code: 'CA', label: 'Canada', currency: 'CAD', locale: 'en-CA' },
		});
		expect(loaded).toEqual(saved);
	});

	it('stores and reads explicit refusal', () => {
		const storage = new MemoryStorage();

		const saved = writeRefusedRegionPreference(storage);

		expect(saved).toEqual({ status: 'refused' });
		expect(readLocalRegionPreference(storage)).toEqual(saved);
	});

	it('returns null for malformed stored values', () => {
		const storage = new MemoryStorage();
		storage.setItem(REGION_STORAGE_KEY, 'not json');

		expect(readLocalRegionPreference(storage)).toBeNull();
	});
});
