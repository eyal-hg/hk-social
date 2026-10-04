// Encrypt the consultants list for the gated site (docs/consultants.html).
//
// The repository and the Netlify site are public and the site gate is client-side only, so the
// list is published ONLY as ciphertext: AES-256-GCM, key = PBKDF2-SHA256(site password, salt).
// The plaintext stays outside the repo (../consultants-leads/consultants.json).
//
// Usage (Eyal runs it and types the site password; nothing is stored, nothing is printed):
//   node scripts/encrypt_consultants.mjs [path/to/consultants.json]
//
// Re-run after the list is updated. The salt is kept between runs, so a browser that already
// opened the list keeps working without typing the password again.
import { createCipheriv, createHash, pbkdf2Sync, randomBytes } from 'node:crypto';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const SRC = resolve(process.argv[2] || resolve(ROOT, '..', 'consultants-leads', 'consultants.json'));
const OUT = process.env.CONSULTANTS_OUT || resolve(ROOT, 'docs', 'consultants.enc.json');
const ITER = 310000;
const FIELDS = ['id', 'name', 'segment', 'phone', 'email', 'website', 'city', 'rating', 'reviews', 'source', 'existing', 'existing_status', 'note'];

function askHidden(prompt) {
  return new Promise((done, fail) => {
    const { stdin, stdout } = process;
    if (!stdin.isTTY) return fail(new Error('צריך להריץ בטרמינל (כדי להקליד את הסיסמה בלי שתוצג).'));
    stdout.write(prompt);
    stdin.setRawMode(true); stdin.resume(); stdin.setEncoding('utf8');
    let buf = '';
    const onData = ch => {
      for (const c of ch) {
        if (c === '\r' || c === '\n') { stdin.setRawMode(false); stdin.pause(); stdin.off('data', onData); stdout.write('\n'); return done(buf); }
        if (c === '\u0003') { stdin.setRawMode(false); stdout.write('\n'); process.exit(130); }
        if (c === '\u007f' || c === '\b') buf = buf.slice(0, -1); else buf += c;
      }
    };
    stdin.on('data', onData);
  });
}

const raw = JSON.parse(readFileSync(SRC, 'utf8'));
const rows = (Array.isArray(raw) ? raw : raw.rows || raw.consultants || []).map(r => Object.fromEntries(FIELDS.map(k => [k, r[k] ?? null])));
if (!rows.length) { console.error('לא נמצאו רשומות ב-' + SRC); process.exit(1); }

// The password must be the site's: compare with the gate hash in site.py so a typo cannot produce a file nobody can open.
const gate = (readFileSync(resolve(ROOT, 'scripts', 'site.py'), 'utf8').match(/GATE_HASH\s*=\s*"([0-9a-f]{64})"/) || [])[1];
const password = process.env.CONSULTANTS_TEST_PASSWORD || await askHidden('סיסמת האתר (לא תוצג): ');
if (!process.env.CONSULTANTS_TEST_PASSWORD && gate && createHash('sha256').update(password, 'utf8').digest('hex') !== gate) {
  console.error('הסיסמה לא תואמת את סיסמת האתר. לא נכתב שום קובץ.'); process.exit(1);
}

let salt = randomBytes(16);
if (existsSync(OUT)) { try { salt = Buffer.from(JSON.parse(readFileSync(OUT, 'utf8')).salt, 'base64'); } catch { /* new salt */ } }
const key = pbkdf2Sync(Buffer.from(password, 'utf8'), salt, ITER, 32, 'sha256');
const iv = randomBytes(12);
const cipher = createCipheriv('aes-256-gcm', key, iv);
const ct = Buffer.concat([cipher.update(gzipSync(Buffer.from(JSON.stringify(rows), 'utf8'))), cipher.final(), cipher.getAuthTag()]);
writeFileSync(OUT, JSON.stringify({ v: 1, kdf: 'PBKDF2-SHA256', iter: ITER, salt: salt.toString('base64'), iv: iv.toString('base64'),
  count: rows.length, updated: new Date().toLocaleString('sv-SE', { timeZone: 'Asia/Jerusalem' }).slice(0, 16), ct: ct.toString('base64') }) + '\n');
console.log(`נכתב ${OUT} · ${rows.length} רשומות · מוצפן. עכשיו אפשר לדחוף.`);
