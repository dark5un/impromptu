/**
 * Voice-following script matcher — vendored, not reinvented.
 *
 * Ported from jlecomte/voice-activated-teleprompter (MIT, © 2024 Julien
 * Lecomte) — see web/static/vendor/NOTICE. That project exists precisely
 * because naive prompters stall when you go off script or mispronounce a word,
 * which is the failure mode the plan calls out, so its matching algorithm is
 * the wheel we want.
 *
 * What changed in the port, and why:
 *   - TypeScript → plain ES modules. The plan mandates no bundler and no npm,
 *     so React/Redux/Vite are dropped; only the three pure functions come over.
 *   - Types became JSDoc. No build step means no type erasure step.
 *
 * The algorithm itself is unchanged: tokenize the reference script once, then
 * for each recognition result compute the Levenshtein distance between what was
 * heard and every candidate prefix of the upcoming reference tokens, and take
 * the closest. Matching a *window* ahead of the last confirmed position is what
 * makes it survive skipped, repeated, and misheard words.
 */

/**
 * @typedef {{type: "TOKEN" | "DELIMITER", value: string, index: number}} TextElement
 */

/**
 * Split text into word tokens and delimiters, preserving token indices.
 *
 * Square-bracketed text is treated as a single DELIMITER so stage directions
 * like `[look at camera]` are displayed but never matched against speech.
 *
 * @param {string | null} text
 * @returns {TextElement[]}
 */
export function tokenize(text) {
  /** @type {TextElement[]} */
  const results = [];
  if (text === null || text === undefined) return results;

  /** @type {TextElement | null} */
  let current = null;
  let i = 0;

  while (i < text.length) {
    let s = text[i];
    let inToken;

    if (s === '[') {
      // A hint runs to the closing bracket; an unclosed bracket stays a
      // one-character delimiter rather than swallowing the rest of the script.
      const hintLength = text.substring(i).indexOf(']');
      s = hintLength > 0 ? text.substring(i, i + hintLength + 1) : s;
      inToken = false;
    } else {
      inToken = /[A-Za-zÀ-ÿА-Яа-я0-9_]/.test(s);
    }

    if (current === null) {
      current = { type: inToken ? 'TOKEN' : 'DELIMITER', value: s, index: 0 };
    } else if (
      (current.type === 'TOKEN' && inToken) ||
      (current.type === 'DELIMITER' && !inToken)
    ) {
      current.value += s;
    } else {
      const lastIndex = current.index;
      results.push(current);
      current = {
        type: inToken ? 'TOKEN' : 'DELIMITER',
        value: s,
        index: lastIndex + 1,
      };
    }

    i += s.length;
  }

  if (current !== null) results.push(current);
  return results;
}

/**
 * Levenshtein edit distance.
 *
 * Vendored from gustf/js-levenshtein (MIT) via the upstream teleprompter.
 * Kept in its optimised four-column form rather than rewritten: it runs on
 * every recognition result, and a naive matrix implementation is the obvious
 * way to make voice-following feel laggy.
 *
 * @param {string} a
 * @param {string} b
 * @returns {number}
 */
export const levenshteinDistance = (function () {
  function min(d0, d1, d2, bx, ay) {
    return d0 < d1 || d2 < d1
      ? d0 > d2
        ? d2 + 1
        : d0 + 1
      : bx === ay
        ? d1
        : d1 + 1;
  }

  return function (a, b) {
    if (a === b) return 0;

    if (a.length > b.length) {
      const tmp = a;
      a = b;
      b = tmp;
    }

    let la = a.length;
    let lb = b.length;

    while (la > 0 && a.charCodeAt(la - 1) === b.charCodeAt(lb - 1)) {
      la--;
      lb--;
    }

    let offset = 0;
    while (offset < la && a.charCodeAt(offset) === b.charCodeAt(offset)) {
      offset++;
    }

    la -= offset;
    lb -= offset;

    if (la === 0 || lb < 3) return lb;

    let x = 0;
    let y;
    let d0, d1, d2, d3;
    let dd = 0;
    let dy;
    let ay;
    let bx0, bx1, bx2, bx3;
    const vector = [];

    for (y = 0; y < la; y++) {
      vector.push(y + 1);
      vector.push(a.charCodeAt(offset + y));
    }

    const len = vector.length - 1;

    for (; x < lb - 3; ) {
      bx0 = b.charCodeAt(offset + (d0 = x));
      bx1 = b.charCodeAt(offset + (d1 = x + 1));
      bx2 = b.charCodeAt(offset + (d2 = x + 2));
      bx3 = b.charCodeAt(offset + (d3 = x + 3));
      dd = x += 4;
      for (y = 0; y < len; y += 2) {
        dy = vector[y];
        ay = vector[y + 1];
        d0 = min(dy, d0, d1, bx0, ay);
        d1 = min(d0, d1, d2, bx1, ay);
        d2 = min(d1, d2, d3, bx2, ay);
        dd = min(d2, d3, dd, bx3, ay);
        vector[y] = dd;
        d3 = d2;
        d2 = d1;
        d1 = d0;
        d0 = dy;
      }
    }

    for (; x < lb; ) {
      bx0 = b.charCodeAt(offset + (d0 = x));
      dd = ++x;
      for (y = 0; y < len; y += 2) {
        dy = vector[y];
        vector[y] = dd = min(dy, d0, dd, bx0, vector[y + 1]);
        d0 = dy;
      }
    }

    return dd;
  };
})();

/**
 * Find how far into the reference script the speaker has got.
 *
 * Only a window starting at the last confirmed position is considered, so the
 * match cost stays bounded no matter how long the script is, and a repeated
 * phrase later in the script cannot yank the position backwards.
 *
 * @param {string} recognized  what the recogniser heard for this utterance
 * @param {TextElement[]} reference  tokenized script (from `tokenize`)
 * @param {number} lastRecognizedTokenIndex  last confirmed token index
 * @returns {number} the new token index
 */
export function computeSpeechRecognitionTokenIndex(
  recognized,
  reference,
  lastRecognizedTokenIndex,
) {
  const recognizedTokens = tokenize(recognized).filter(
    (element) => element.type === 'TOKEN',
  );

  const comparisonString = recognizedTokens
    .reduce((accumulator, token) => accumulator + ' ' + token.value, '')
    .replace(/\s+/, ' ')
    .trim();

  if (lastRecognizedTokenIndex < 0) lastRecognizedTokenIndex = 0;

  // Window: twice what was heard, plus slack, so skipping a few words still
  // lands inside the candidate set.
  const referenceTokens = reference
    .slice(
      lastRecognizedTokenIndex,
      lastRecognizedTokenIndex + recognizedTokens.length * 2 + 10,
    )
    .filter((element) => element.type === 'TOKEN');

  /** @type {number[]} */
  const distances = [];
  let i = 0;

  while (++i <= referenceTokens.length) {
    const referenceSubstring = referenceTokens
      .slice(0, i)
      .reduce((accumulator, token) => accumulator + ' ' + token.value, '')
      .replace(/\s+/, ' ')
      .trim();
    distances.push(levenshteinDistance(comparisonString, referenceSubstring));
  }

  const index = distances.indexOf(Math.min(...distances));
  const token = referenceTokens[index];

  return token ? token.index : lastRecognizedTokenIndex;
}
