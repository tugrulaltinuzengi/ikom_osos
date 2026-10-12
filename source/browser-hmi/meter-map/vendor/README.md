# Vendored libraries

| File | What | Version | License |
|---|---|---|---|
| `pdf.min.js`, `pdf.worker.min.js` | [PDF.js](https://github.com/mozilla/pdf.js), legacy build (older browsers and Android WebView) | pdfjs-dist 3.11.174 | Apache-2.0 (`LICENSE-pdfjs`) |

PDF.js reads the text out of an uploaded PDF register map. It runs entirely in
the page (or the app's WebView): the document is never uploaded anywhere.

To update: `npm pack pdfjs-dist@<version>`, copy `legacy/build/pdf.min.js` and
`legacy/build/pdf.worker.min.js` here, and run the tests in `../tests`.
