import { describe, it, expect } from 'vitest';
import { getDeviceLabel } from '../device-label';

describe('getDeviceLabel', () => {
  it('parses Chrome on Android', () => {
    expect(getDeviceLabel('Mozilla/5.0 (Linux; Android 13) Chrome/120.0')).toBe('Android · Chrome');
  });
  it('parses Safari on iPhone', () => {
    expect(getDeviceLabel('Mozilla/5.0 (iPhone) Safari/17.0')).toBe('iPhone · Safari');
  });
  it('parses Edge on Windows', () => {
    expect(getDeviceLabel('Mozilla/5.0 (Windows NT 10.0) Edg/120.0')).toBe('Windows · Edge');
  });
  it('falls back when nothing matches', () => {
    expect(getDeviceLabel('totally-unknown-ua')).toBe('Unbekanntes Gerät');
  });
});
