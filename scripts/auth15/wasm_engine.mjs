// Socket-free supplemental PostgreSQL WASM engine; never a production store.
import readline from 'node:readline';
import {pathToFileURL} from 'node:url';
const {PGlite}=await import(pathToFileURL(process.argv[2]+'/dist/index.js').href);
const db=new PGlite();await db.waitReady;
const lines=readline.createInterface({input:process.stdin,crlfDelay:Infinity});
for await (const line of lines) {
 try {
  const {sql,params}=JSON.parse(line);
  const result=params?.length?await db.query(sql,params):(await db.exec(sql)).at(-1)??{rows:[]};
  process.stdout.write(JSON.stringify({result})+'\n');
 }catch(e){process.stdout.write(JSON.stringify({error:{message:e.message,code:e.code}})+'\n');}
}
await db.close();
