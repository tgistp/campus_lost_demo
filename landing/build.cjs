const esbuild = require('esbuild');
const fs=require('node:fs');
fs.mkdirSync('dist',{recursive:true});
esbuild.buildSync({entryPoints:['src/main.jsx'],bundle:true,minify:true,outfile:'dist/app.js',jsx:'automatic',legalComments:'linked',define:{'process.env.NODE_ENV':'"production"'},target:['es2022']});
fs.writeFileSync('dist/index.html',`<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'none'; base-uri 'none'; form-action 'none'"><title>PNU:LINK</title><link rel="stylesheet" href="./app.css"></head><body><div id="root"></div><script src="./app.js"></script></body></html>`);
fs.copyFileSync('src/vendor/LICENSE.md','dist/REACT_BITS_LICENSE.md');
