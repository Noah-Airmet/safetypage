// The search grammar as worked examples: each one runs on press. The landing page's popover and
// the empty search page both show it.
export const big = (documents: number) => documents > 1000;
export const GRAMMAR: [string, string][] = [
  ['sandbagging', 'Pages with that word. Capitals don’t matter.'],
  ['sabotage evaluation', 'Pages with all of the words, in any order.'],
  ['"alignment faking"', 'The exact phrase.'],
  ['sparse autoencoder*', 'Any word that starts that way.'],
  ['sycophancy NEAR/10 evaluation', 'Both words within ten words of each other.'],
  ['"model welfare" -consciousness', 'Leave out pages with a word.'],
];
// A small test library has none of those words.
export const GRAMMAR_SMALL: [string, string][] = [
  ['evaluation', 'Pages with that word. Capitals don’t matter.'],
  ['"risk assessment" evaluation', 'The exact phrase, and a word.'],
  ['sparse autoencoder*', 'Any word that starts that way.'],
];
export const CHECK_EXAMPLE = `Model evaluation matters, but its authors do not oversell it. They write that it is "not the only tool available for AI risk assessment" (arxiv:2305.15324/v2/p6), and they call it "one of the main tools we have for AI risk assessment" (arxiv:2305.15324/v2/p3).

A looser summary claims that "Model evaluation is the only tool available for AI risk assessment" (arxiv:2305.15324/v2/p6). Cunningham et al. propose sparse autoencoders as an answer to polysemantic neurons (arxiv:2309.08600/v3/p2), and one version of this paragraph cited a page that does not exist (arxiv:2305.15324/v2/p41).`;
// What the checker does, for its ? (help behind a closed disclosure).
export const CHECK_TERMS: [string, string][] = [
  ['Verified', 'The quoted words are on the cited page.'],
  ['Page only', 'The page is real; nothing was quoted from it.'],
  ['Rejected', 'Anything else, with the reason and what the page says.'],
  ['The check', 'Code, not a model. It does not judge whether the page supports the claim.'],
];
