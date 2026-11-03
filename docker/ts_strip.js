// TypeScript to JavaScript for the code runner: the types are stripped by the compiler's own transpileModule,
// with no type checking, so an answer's `require` or a type package that is not here does not stop it from
// running. Only syntax errors stop it.  usage: node ts_strip.js main.ts main.js
"use strict";
const fs = require("fs");
const ts = require("typescript");

const [src, out] = process.argv.slice(2);
const res = ts.transpileModule(fs.readFileSync(src, "utf8"), {
  compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS, esModuleInterop: true },
  reportDiagnostics: true,
  fileName: src,
});
const errors = (res.diagnostics || []).filter((d) => d.category === ts.DiagnosticCategory.Error);
for (const d of errors) {
  const where = d.file && d.start !== undefined ? d.file.getLineAndCharacterOfPosition(d.start) : null;
  console.error(`${src}${where ? `:${where.line + 1}:${where.character + 1}` : ""}: error: ` +
                ts.flattenDiagnosticMessageText(d.messageText, "\n"));
}
if (errors.length) process.exit(1);
fs.writeFileSync(out, res.outputText);
