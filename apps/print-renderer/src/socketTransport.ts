/** Private filesystem HTTP endpoint. Caller holds renderer.lock via flock. */
import * as fs from 'node:fs';
import {dirname, isAbsolute, normalize, join} from 'node:path/posix';
import {createConnection} from 'node:net';
import type {Server} from 'node:http';

export function validateSocketDirectory(path: string): void {
  if (!isAbsolute(path) || normalize(path) !== path || path.includes('\0') || Buffer.byteLength(path)>100)
    throw new Error('renderer_socket_invalid_path');
  const directory=dirname(path);
  if (fs.realpathSync(directory)!==directory) throw new Error('renderer_socket_symlink_noncanonical_directory');
  const st=fs.lstatSync(directory);
  if (!st.isDirectory() || st.uid!==process.getuid!() || st.gid!==process.getgid!() || (st.mode & 0o7777)!==0o750)
    throw new Error('renderer_socket_directory_permission_mode');
}

export function ensureSocketLock(path: string): void {
  validateSocketDirectory(path);
  const lock=join(dirname(path),'renderer.lock');
  try {const fd=fs.openSync(lock,'wx',0o600);fs.closeSync(fd);}
  catch(error) {if ((error as NodeJS.ErrnoException).code!=='EEXIST') throw error;}
  const st=fs.lstatSync(lock);
  if (!st.isFile() || st.isSymbolicLink() || st.uid!==process.getuid!() || st.gid!==process.getgid!() || (st.mode & 0o7777)!==0o600)
    throw new Error('renderer_socket_unsafe_lock');
}

function probeSocket(path: string): Promise<void> {
  return new Promise((resolve,reject)=>{
    const socket=createConnection({path});
    socket.setTimeout(1000);
    socket.once('connect',()=>{socket.destroy();resolve();});
    socket.once('error',reject);
    socket.once('timeout',()=>{socket.destroy();reject(new Error('renderer_socket_probe_timeout'));});
  });
}

export async function prepareSocketPath(path: string, probe=probeSocket): Promise<void> {
  validateSocketDirectory(path);
  let st: fs.Stats;
  try {st=fs.lstatSync(path);}
  catch(error) {if ((error as NodeJS.ErrnoException).code==='ENOENT') return;throw error;}
  if (!st.isSocket() || st.isSymbolicLink() || st.uid!==process.getuid!() || st.gid!==process.getgid!())
    throw new Error('renderer_socket_unsafe_existing_endpoint');
  try {await probe(path);}
  catch(error) {
    if ((error as NodeJS.ErrnoException).code!=='ECONNREFUSED') throw error;
    const now=fs.lstatSync(path);
    if (!now.isSocket() || now.ino!==st.ino || now.dev!==st.dev || now.uid!==st.uid)
      throw new Error('renderer_socket_changed_during_probe');
    fs.unlinkSync(path);return;
  }
  throw new Error('renderer_socket_active_endpoint');
}

export async function listenOnSocket(server: Server, path: string): Promise<void> {
  await prepareSocketPath(path);
  await new Promise<void>((resolve,reject)=>{
    server.once('error',reject);
    const old=process.umask(0o077);
    try {
      server.listen({path,backlog:32},()=>{
        try {fs.chmodSync(path,0o660);server.removeListener('error',reject);resolve();}
        catch(error) {server.close();reject(error);}
      });
    } finally {process.umask(old);}
  });
}

// Entrypoint preflight: only operator config controls this path.
if (require.main===module) {
  ensureSocketLock(process.env.CISSTAT_PRINT_RENDERER_SOCKET || '');
}
