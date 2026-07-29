const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const FORBIDDEN_KEYS = new Set([
  'api_key',
  'openrouter_api_key',
  'authorization',
  'raw_upload',
  'raw_data',
  'stored_document_text',
  'stored_chunk_content'
]);

function inspectKeys(obj, pathPrefix = '') {
  if (obj === null || typeof obj !== 'object') {
    return;
  }
  for (const key of Object.keys(obj)) {
    const fullPath = pathPrefix ? `${pathPrefix}.${key}` : key;
    const lowerKey = key.toLowerCase();
    if (FORBIDDEN_KEYS.has(lowerKey)) {
      throw new Error(`Forbidden field class detected: '${key}' at '${fullPath}'`);
    }
    inspectKeys(obj[key], fullPath);
  }
}

test('privacy prohibition check', () => {
  const subjectPath = process.env.GSD_PROHIB_SUBJECT || path.join(__dirname, 'fixtures', 'phase02_privacy_clean.json');
  const content = fs.readFileSync(subjectPath, 'utf8');
  const json = JSON.parse(content);
  inspectKeys(json);
});
