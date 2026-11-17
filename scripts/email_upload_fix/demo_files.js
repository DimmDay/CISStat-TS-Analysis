// Execute the actual UI generators: no copied CSV fixture or invented dataset.
const fs = require("node:fs");
const ts = require("typescript");
const vm = require("node:vm");
const path = require("node:path");
const source = fs.readFileSync(path.join(__dirname, "../../packages/ui/lib/demoDatasets.ts"), "utf8");
const code = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS}}).outputText;
const exportsObject = {};
vm.runInNewContext(code, {exports: exportsObject, File});
Promise.all(exportsObject.DEMO_DATASETS.map(async dataset => {
  const file = exportsObject.demoDatasetToFile(dataset);
  return {id: dataset.id, name: file.name, csv: await file.text()};
})).then(files => process.stdout.write(JSON.stringify(files))).catch(error => { console.error(error); process.exitCode = 1; });
