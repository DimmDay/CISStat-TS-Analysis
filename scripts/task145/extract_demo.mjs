import { writeFileSync, mkdirSync } from 'node:fs';
import { DEMO_DATASETS as demoDatasets, demoDatasetToFile } from '../../packages/ui/lib/demoDatasets.ts';
mkdirSync(new URL('./calib_data/', import.meta.url), { recursive: true });
for (const ds of demoDatasets) {
  const file = demoDatasetToFile(ds);
  const buf = Buffer.from(await file.arrayBuffer());
  writeFileSync(new URL(`./calib_data/${ds.fileName}`, import.meta.url), buf);
  console.log(ds.id, ds.fileName, buf.length, 'bytes');
}
