import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
const template = fs.readFileSync(path.join(import.meta.dirname, 'template.html'), 'utf8');
const volumeDirs = fs.readdirSync(root, { withFileTypes: true })
  .filter((item) => item.isDirectory() && /^\d+_Volume_/.test(item.name));

// ---- Build chapter data ----
const chapters = [];
for (const volume of volumeDirs) {
  const volumePath = path.join(root, volume.name);
  for (const item of fs.readdirSync(volumePath, { withFileTypes: true })) {
    if (!item.isDirectory() || !/^Chapter-\d+_/.test(item.name)) continue;
    const folder = path.join(volumePath, item.name);
    const number = item.name.match(/^Chapter-(\d+)/)?.[1] || '00';
    const read = (suffix = '') => {
      const file = path.join(folder, `Chapter-${number}${suffix}.md`);
      return fs.existsSync(file) ? fs.readFileSync(file, 'utf8') : '';
    };
    const main = read();
    const headings = [...main.matchAll(/^\\?## Topic \d+:\s*(.+)$/gm)].map((m) => m[1].trim());
    const chapterTitle = [...main.matchAll(/^\\?#\s+(.+)$/gm)]
      .map((match) => match[1].trim())
      .find((heading) => !/^Chapter\s+\d+$/i.test(heading));
    chapters.push({
      id: `${volume.name}/${item.name}`,
      volume: volume.name.replace(/^\d+_Volume_/, '').replaceAll('_', ' '),
      number: Number(number),
      slug: item.name.replace(/^Chapter-\d+_/, '').toLowerCase().replaceAll('_', '-'),
      title: chapterTitle || item.name.replace(/^Chapter-\d+_/, '').replaceAll('_', ' '),
      topics: headings,
      content: main,
      mcq: read('_MCQ'),
      viva: read('_Viva'),
      glossary: read('_Glossary'),
      references: read('_References'),
      videos: read('_Videos')
    });
  }
}
chapters.sort((a, b) => a.number - b.number);

// ---- 1. Generate assets/data.js (chapter data as separate JS file) ----
const payload = JSON.stringify(chapters).replaceAll('</script', '<\\/script');
fs.mkdirSync(path.join(import.meta.dirname, 'assets'), { recursive: true });
fs.writeFileSync(
  path.join(import.meta.dirname, 'assets', 'data.js'),
  `window.BOOK_DATA=${payload};`
);

// ---- 2. Generate index.html (HTML + links to CSS/JS/data) ----
// The split-template script already created assets/styles.css and assets/app.js
// from the template. This build script ensures assets/data.js is fresh, and the
// index.html references all three: styles.css, data.js, app.js.
let indexHtml = fs.readFileSync(path.join(import.meta.dirname, 'index.html'), 'utf8');
// Make sure data.js is loaded (if it somehow got dropped)
if (!indexHtml.includes('assets/data.js')) {
  indexHtml = indexHtml.replace('<script src="assets/app.js"></script>', '<script src="assets/data.js"></script>\n<script src="assets/app.js"></script>');
}
fs.writeFileSync(path.join(import.meta.dirname, 'index.html'), indexHtml);

// ---- 3. Generate self-contained single-file versions (optional) ----
let built = fs.readFileSync(path.join(import.meta.dirname, 'index.html'), 'utf8');
built = built.replace(/<link rel="stylesheet" href="assets\/styles\.css(?:\?v=[^"]+)?">/, () => `<style>${fs.readFileSync(path.join(import.meta.dirname, 'assets', 'styles.css'), 'utf8')}</style>`);
built = built.replace(/<script src="assets\/data\.js(?:\?v=[^"]+)?"><\/script>/, () => `<script>${fs.readFileSync(path.join(import.meta.dirname, 'assets', 'data.js'), 'utf8')}</script>`);
built = built.replace(/<script src="assets\/app\.js(?:\?v=[^"]+)?"><\/script>/, () => `<script>${fs.readFileSync(path.join(import.meta.dirname, 'assets', 'app.js'), 'utf8')}</script>`);
fs.writeFileSync(path.join(import.meta.dirname, 'eee-career-masterbook-self-contained.html'), built);
const bloggerBuilt = built.replace(
  '</title>',
  '</title>\n<style>html,body{margin:0;padding:0;background:#f5f8f8}</style>'
);
fs.writeFileSync(path.join(import.meta.dirname, 'eee-career-masterbook-blogger.html'), bloggerBuilt);

console.log(`Built ${chapters.length} chapter(s)`);
console.log('  → blogger-web/index.html (links styles.css, data.js, app.js)');
console.log('  → blogger-web/assets/data.js');
console.log('  → blogger-web/eee-career-masterbook-self-contained.html');
