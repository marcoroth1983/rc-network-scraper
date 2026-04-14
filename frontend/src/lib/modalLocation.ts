import type { Location } from 'react-router-dom';

export interface ModalState {
  background?: Location;
  isDirectHit?: boolean;
}

export function getBackground(loc: Location): Location | undefined {
  return (loc.state as ModalState | null)?.background;
}

export function isDirectHit(loc: Location): boolean {
  return (loc.state as ModalState | null)?.isDirectHit === true;
}
