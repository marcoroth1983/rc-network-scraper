// Must mirror backend/app/analysis/vocabulary.py — update both when vocabulary changes.

export const MODEL_TYPES = [
  "airplane", "helicopter", "multicopter", "glider", "boat", "car",
] as const;

export type ModelType = typeof MODEL_TYPES[number];

export const MODEL_SUBTYPES: Record<ModelType, string[]> = {
  airplane: ["jet", "warbird", "trainer", "scale", "3d", "nurflügler",
    "hochdecker", "tiefdecker", "mitteldecker", "delta", "biplane",
    "aerobatic", "kit", "hotliner", "funflyer", "speed", "pylon"],
  helicopter: ["700", "580", "600", "550", "500", "450", "420", "380", "scale"],
  multicopter: ["quadcopter", "hexacopter", "fpv"],
  glider: ["thermik", "hotliner", "f3b", "f3k", "f3j", "f5j", "f5b", "f5k",
    "f3f", "f3l", "hangflug", "dlg", "scale", "motorglider"],
  boat: ["rennboot", "segelboot", "schlepper", "submarine", "yacht"],
  car: ["buggy", "monstertruck", "crawler", "tourenwagen", "truggy", "drift"],
};

export const MODEL_TYPE_LABELS: Record<ModelType, string> = {
  airplane: "Flugzeug",
  helicopter: "Hubschrauber",
  multicopter: "Multicopter",
  glider: "Segler",
  boat: "Boot",
  car: "Auto",
};

// Which model_types are meaningful for each category.
// rc-cars → only car, schiffsmodelle → only boat are fully implied by the category
// and hidden to avoid redundancy. flugmodelle and "all"/other categories show all flying types.
export const CATEGORY_MODEL_TYPES: Partial<Record<string, ModelType[]>> = {
  flugmodelle:    ['airplane', 'helicopter', 'multicopter', 'glider'],
  'rc-cars':        [],   // fully implied by category — section hidden
  schiffsmodelle: [],   // fully implied by category — section hidden
};

// Returns the model_types to show for the given category key.
// Returns all 6 types for categories without a mapping (antriebstechnik, rc-elektronik, etc.)
export function availableModelTypes(category: string): ModelType[] {
  if (category in CATEGORY_MODEL_TYPES) {
    return CATEGORY_MODEL_TYPES[category] ?? [];
  }
  return [...MODEL_TYPES];
}
