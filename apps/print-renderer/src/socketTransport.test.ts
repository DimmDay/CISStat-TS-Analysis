/** @jest-environment node */
// Filesystem doubles on both CI OSes; real Linux UID/mode/flock/UDS is a VM gate.
import * as T from './socketTransport';
const fs=require('node:fs');
const path='/run/cisstat-renderer/render.sock',dir='/run/cisstat-renderer';
let files:Map<string,any>;
let uidDescriptor:PropertyDescriptor|undefined,gidDescriptor:PropertyDescriptor|undefined;
function node(kind:string,mode:number,extra:any={}) {
  return {uid:10001,gid:10001,mode,ino:1,dev:1,
    isDirectory:()=>kind==='dir',isFile:()=>kind==='file',isSocket:()=>kind==='socket',isSymbolicLink:()=>kind==='link',...extra};
}
beforeEach(()=>{
  uidDescriptor=Object.getOwnPropertyDescriptor(process,'getuid');gidDescriptor=Object.getOwnPropertyDescriptor(process,'getgid');
  Object.defineProperty(process,'getuid',{value:()=>10001,configurable:true});Object.defineProperty(process,'getgid',{value:()=>10001,configurable:true});
  files=new Map([[dir,node('dir',0o40750)]]);
  jest.spyOn(fs,'realpathSync').mockImplementation((p:any)=>p===dir+'-link'?dir:p);
  jest.spyOn(fs,'lstatSync').mockImplementation((p:any)=>{if(!files.has(p))throw Object.assign(new Error('missing'),{code:'ENOENT'});return files.get(p);});
  jest.spyOn(fs,'openSync').mockImplementation((p:any,_flags:any,mode:any)=>{if(files.has(p))throw Object.assign(new Error('exists'),{code:'EEXIST'});files.set(p,node('file',0o100000|mode));return 77;});
  jest.spyOn(fs,'closeSync').mockImplementation(()=>{});
  jest.spyOn(fs,'unlinkSync').mockImplementation((p:any)=>{files.delete(p);});
});
afterEach(()=>{
  jest.restoreAllMocks();
  if(uidDescriptor)Object.defineProperty(process,'getuid',uidDescriptor);else delete (process as any).getuid;
  if(gidDescriptor)Object.defineProperty(process,'getgid',gidDescriptor);else delete (process as any).getgid;
});
test('private owned directory and lock accepted',()=>{
  T.validateSocketDirectory(path);T.ensureSocketLock(path);
  expect(files.get(dir+'/renderer.lock').mode&0o777).toBe(0o600);
});
test.each([0o777,0o770,0o755,0o2750])('directory mode %s fails closed',mode=>{
  files.set(dir,node('dir',0o40000|mode));expect(()=>T.validateSocketDirectory(path)).toThrow(/permission|mode/);
});
test('symlink directory and noncanonical paths fail',()=>{
  expect(()=>T.validateSocketDirectory(dir+'-link/render.sock')).toThrow(/symlink|canonical/);
  expect(()=>T.validateSocketDirectory('relative.sock')).toThrow();
});
test('regular file and symlink endpoint survive refusal',async()=>{
  for(const kind of ['file','link']){
    const original=node(kind,0o100600);files.set(path,original);
    await expect(T.prepareSocketPath(path)).rejects.toThrow(/socket|unsafe/);
    expect(files.get(path)).toBe(original);
  }
});
test('missing socket needs no unlink',async()=>{await T.prepareSocketPath(path);expect(fs.unlinkSync).not.toHaveBeenCalled();});
test('active endpoint or ambiguous error never unlinks',async()=>{
  files.set(path,node('socket',0o140660));
  await expect(T.prepareSocketPath(path,async()=>{})).rejects.toThrow(/active/);
  await expect(T.prepareSocketPath(path,async()=>{throw Object.assign(new Error('denied'),{code:'EACCES'});})).rejects.toThrow('denied');
  expect(files.has(path)).toBe(true);
});
test('only refused owned same-inode stale socket removed',async()=>{
  files.set(path,node('socket',0o140660));
  await T.prepareSocketPath(path,async()=>{throw Object.assign(new Error('refused'),{code:'ECONNREFUSED'});});
  expect(files.has(path)).toBe(false);
});
test('changed endpoint is never deleted',async()=>{
  files.set(path,node('socket',0o140660));
  await expect(T.prepareSocketPath(path,async()=>{
    files.set(path,node('socket',0o140660,{ino:2}));throw Object.assign(new Error('refused'),{code:'ECONNREFUSED'});
  })).rejects.toThrow(/changed/);
  expect(files.get(path).ino).toBe(2);
});
test('foreign UID or unsafe lock fails closed',async()=>{
  files.set(path,node('socket',0o140660,{uid:0}));
  await expect(T.prepareSocketPath(path)).rejects.toThrow(/unsafe/);
  files.set(dir+'/renderer.lock',node('link',0o120777));expect(()=>T.ensureSocketLock(path)).toThrow(/unsafe_lock/);
});
