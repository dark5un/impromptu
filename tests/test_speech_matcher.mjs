// Behaviour tests for the vendored speech matcher (node --test, no npm).
//
// These pin the *robustness* claims that justified vendoring this algorithm
// instead of writing a naive word-pointer: going off script, mispronouncing,
// skipping ahead and repeating yourself must all still track. A simple
// "advance when the next word matches" prompter fails every case below, which
// is exactly the stall the plan cites.
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  computeSpeechRecognitionTokenIndex,
  levenshteinDistance,
  tokenize,
} from '../web/static/vendor/speech-matcher.js';

const SCRIPT =
  'Immutable infrastructure changes everything about how we deploy software today';

/** Token index -> the word at that index, for readable assertions. */
function wordAt(reference, index) {
  const element = reference.find((e) => e.index === index);
  return element ? element.value : null;
}

test('tokenize separates words from delimiters and indexes them', () => {
  const elements = tokenize('hello, world');
  const tokens = elements.filter((e) => e.type === 'TOKEN');
  assert.deepEqual(
    tokens.map((t) => t.value),
    ['hello', 'world'],
  );
  // Indices are monotonic across tokens AND delimiters, which is what lets the
  // matcher map a match back to a position in the displayed script.
  assert.ok(tokens[1].index > tokens[0].index);
});

test('bracketed stage directions are never matched against speech', () => {
  const elements = tokenize('Say this [look at camera] and this');
  // The hint is absorbed into the surrounding delimiter run. What matters is
  // the contract that none of its words become matchable tokens.
  assert.ok(
    elements.some(
      (e) => e.type === 'DELIMITER' && e.value.includes('[look at camera]'),
    ),
    'the bracketed span must live inside a delimiter, not a token',
  );
  assert.ok(
    !elements.some((e) => e.type === 'TOKEN' && e.value === 'camera'),
    'words inside a hint must not become tokens',
  );
  assert.deepEqual(
    elements.filter((e) => e.type === 'TOKEN').map((t) => t.value),
    ['Say', 'this', 'and', 'this'],
  );
});

test('an unclosed bracket does not swallow the rest of the script', () => {
  // Divergence from upstream, deliberate: upstream would consume everything
  // after a stray '[', silently dropping the remaining words from matching.
  const elements = tokenize('before [ after words');
  const tokens = elements.filter((e) => e.type === 'TOKEN').map((t) => t.value);
  assert.deepEqual(tokens, ['before', 'after', 'words']);
});

test('levenshtein distance is zero for identical and symmetric otherwise', () => {
  assert.equal(levenshteinDistance('abc', 'abc'), 0);
  assert.equal(levenshteinDistance('kitten', 'sitting'), 3);
  assert.equal(
    levenshteinDistance('sitting', 'kitten'),
    levenshteinDistance('kitten', 'sitting'),
  );
  assert.equal(levenshteinDistance('', 'abc'), 3);
});

test('exact reading advances the position to the words spoken', () => {
  const reference = tokenize(SCRIPT);
  const index = computeSpeechRecognitionTokenIndex(
    'immutable infrastructure changes',
    reference,
    0,
  );
  assert.equal(wordAt(reference, index), 'changes');
});

test('a mispronounced word still tracks instead of stalling', () => {
  // "infrastructur" is a plausible recogniser error; a naive matcher stops dead.
  const reference = tokenize(SCRIPT);
  const index = computeSpeechRecognitionTokenIndex(
    'immutable infrastructur changes',
    reference,
    0,
  );
  assert.equal(wordAt(reference, index), 'changes');
});

test('going off script does not move the position backwards', () => {
  const reference = tokenize(SCRIPT);
  const start = computeSpeechRecognitionTokenIndex(
    'immutable infrastructure changes',
    reference,
    0,
  );
  const after = computeSpeechRecognitionTokenIndex(
    'you know what I mean right',
    reference,
    start,
  );
  assert.ok(
    after >= start,
    `improvising must not rewind the prompter (${start} -> ${after})`,
  );
});

test('a partial utterance advances proportionally, not to the end', () => {
  // Prefixes are always measured from the last confirmed position, so reading
  // the first few words advances a few tokens and no further.
  const reference = tokenize(SCRIPT);
  const index = computeSpeechRecognitionTokenIndex(
    'immutable infrastructure',
    reference,
    0,
  );
  assert.equal(wordAt(reference, index), 'infrastructure');
});

test('KNOWN LIMITATION: jumping far ahead off-script does not leap forward', () => {
  // Documented, not a defect to fix here. The algorithm scores candidate
  // PREFIXES starting at the last confirmed position, so it models sequential
  // reading. Saying a phrase from the middle of the script while the prompter
  // sits at the top stays put rather than leaping.
  //
  // This is the correct trade-off for a prompter: leaping on any fuzzy
  // mid-script match is exactly how other prompters lose their place when you
  // repeat a common phrase. Manual seek is the intended escape hatch, which is
  // why the phone remote keeps its seek buttons.
  const reference = tokenize(SCRIPT);
  const index = computeSpeechRecognitionTokenIndex(
    'about how we deploy',
    reference,
    0,
  );
  assert.equal(wordAt(reference, index), 'Immutable');
});

test('matching is relative to the last position, so repeats do not jump', () => {
  const repetitive = tokenize('deploy the thing and then deploy the thing again');
  // Starting late, "deploy the thing" must resolve against the SECOND
  // occurrence, not snap back to the first.
  const late = repetitive.find((e) => e.value === 'then').index;
  const index = computeSpeechRecognitionTokenIndex(
    'deploy the thing',
    repetitive,
    late,
  );
  assert.ok(
    index >= late,
    `a repeated phrase must not rewind the prompter (${late} -> ${index})`,
  );
});

test('empty recognition leaves the position untouched', () => {
  const reference = tokenize(SCRIPT);
  assert.equal(computeSpeechRecognitionTokenIndex('', reference, 4), 4);
});

test('a negative starting index is clamped rather than throwing', () => {
  const reference = tokenize(SCRIPT);
  const index = computeSpeechRecognitionTokenIndex(
    'immutable',
    reference,
    -5,
  );
  assert.ok(index >= 0);
});

test('the matcher is bounded by the window, not the script length', () => {
  // A very long script must not make one utterance arbitrarily expensive:
  // the candidate set is derived from what was heard, not from the script.
  const long = tokenize(Array.from({ length: 5000 }, () => 'word').join(' '));
  const started = process.hrtime.bigint();
  computeSpeechRecognitionTokenIndex('word word word', long, 0);
  const elapsedMs = Number(process.hrtime.bigint() - started) / 1e6;
  assert.ok(elapsedMs < 250, `matching took ${elapsedMs.toFixed(1)}ms`);
});

// ── resync: deliberately widen the search to the whole script ───────────────

test('default matching does not rewind when speaking an earlier phrase', () => {
  // The prompter is late; the speaker reads the headline from the TOP. Without
  // resync the window stays put (the documented trade-off): no jumping back.
  const reference = tokenize(SCRIPT);
  const late = reference.find((e) => e.value === 'everything').index;
  const normal = computeSpeechRecognitionTokenIndex(
    'immutable infrastructure changes',
    reference,
    late,
  );
  assert.ok(normal >= late, `without resync the prompter must not rewind (${normal})`);
});

test('resync windowStart=0 searches the whole script and jumps to the phrase', () => {
  // The resync button's contract: for ONE utterance the window widens to the
  // whole script, so a reader who fell behind (or jumped ahead) can be brought
  // back to where they actually are. windowStart=0 is the explicit opt-out of
  // the anti-rewind guarantee.
  const reference = tokenize(SCRIPT);
  const late = reference.find((e) => e.value === 'everything').index;
  const resynced = computeSpeechRecognitionTokenIndex(
    'immutable infrastructure changes',
    reference,
    late,
    /* windowStart */ 0,
  );
  assert.ok(resynced >= 0, 'resync must find a token in the whole script');
  assert.ok(
    resynced < late,
    `resync must jump back to the spoken phrase (${resynced} vs ${late})`,
  );
  assert.equal(wordAt(reference, resynced), 'changes');
});

test('resync still advances to the spoken words, not the start', () => {
  // Even with the window widened, matching stays sequential: reading the first
  // few words advances a few tokens, it does not snap to the script start.
  const reference = tokenize(SCRIPT);
  const index = computeSpeechRecognitionTokenIndex(
    'immutable infrastructure changes',
    reference,
    0,
    /* windowStart */ 0,
  );
  assert.equal(wordAt(reference, index), 'changes');
});
