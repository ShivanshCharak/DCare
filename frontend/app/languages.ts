export const OUTPUT_LANGUAGES = [
  { code: "en", name: "English" },
  { code: "hi", name: "Hindi" },
  { code: "bn", name: "Bengali" },
  { code: "gu", name: "Gujarati" },
  { code: "kn", name: "Kannada" },
  { code: "ml", name: "Malayalam" },
  { code: "mr", name: "Marathi" },
  { code: "or", name: "Odia" },
  { code: "pa", name: "Punjabi" },
  { code: "ta", name: "Tamil" },
  { code: "te", name: "Telugu" },
] as const;

export const LANGUAGE_NAMES: Record<string, string> = Object.fromEntries(
  OUTPUT_LANGUAGES.map(({ code, name }) => [code, name]),
);
