/** The museum a counter/gate device works for, remembered on the device. */
const KEY = 'aa_gate_museum';

export const gateMuseum = {
  get(): string {
    try {
      return localStorage.getItem(KEY) ?? '';
    } catch {
      return '';
    }
  },
  set(slug: string): void {
    try {
      localStorage.setItem(KEY, slug);
    } catch {
      /* storage unavailable: the page keeps it in state only */
    }
  },
};
