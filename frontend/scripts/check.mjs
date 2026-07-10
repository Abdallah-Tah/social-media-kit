import { existsSync } from 'node:fs';
const mode = process.argv[2] || 'check';
if (!existsSync(new URL('../dist/index.html', import.meta.url))) {
  console.error('frontend/dist/index.html is missing');
  process.exit(1);
}
console.log(`${mode} ok`);
