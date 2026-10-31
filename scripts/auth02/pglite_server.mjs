// Optional PostgreSQL WASM test transport. Never an application server/backend.
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
const [modules, dataDir, rawPort]=process.argv.slice(2);
const require=createRequire(resolve(modules,'auth02-harness.cjs'));
const {PGlite}=require('@electric-sql/pglite');
const {PGLiteSocketServer}=require('@electric-sql/pglite-socket');
const db=await PGlite.create({dataDir});
console.log(JSON.stringify((await db.query('SELECT version()')).rows));
const server=new PGLiteSocketServer({db,host:'127.0.0.1',port:Number(rawPort),maxConnections:10});
await server.start();console.log('AUTH02_PGLITE_READY');
for(const signal of ['SIGINT','SIGTERM'])process.on(signal,async()=>{
  await server.stop();await db.close();process.exit(0);
});
