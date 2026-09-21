import { mkdir, copyFile } from 'node:fs/promises';

// Publish only the self-contained page; keep scripts and sample data private to the repository.
await mkdir('public', { recursive: true });
await copyFile('index.html', 'public/index.html');
console.log('Static page built: public/index.html');
