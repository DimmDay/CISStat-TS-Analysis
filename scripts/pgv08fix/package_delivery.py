"""Package only this detached worktree's changed files; never node_modules/dist."""
import subprocess,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT.parent/'upload/cisstat-pgv08-fix-recert-bddc180.zip'
def git(*args):
 return subprocess.check_output(['git',*args],cwd=ROOT,text=True).splitlines()
files=set(git('diff','--name-only'))|set(git('ls-files','--others','--exclude-standard'))
files={p for p in files if p!='node_modules' and 'node_modules' not in Path(p).parts and not p.endswith(('.pid','cold_launch.sh')) and 'jest_baseline_ready' not in p}
files.add('scripts/pgv08fix/files.txt')
for p in files:
 assert not Path(p).is_absolute() and '..' not in Path(p).parts
 if p!='scripts/pgv08fix/files.txt':assert (ROOT/p).is_file() and not (ROOT/p).is_symlink(),p
(ROOT/'scripts/pgv08fix/files.txt').write_text('\n'.join(sorted(files))+'\n')
for p in ['apps/print-renderer/build/Dockerfile','apps/print-renderer/build/deployment/docker-compose.yml','apps/print-renderer/build/deployment/README.md','scripts/pgv08/protocols/server_main.log','scripts/pgv08/protocols/server_dependency.log']:
 assert p in files,p
 assert subprocess.run(['git','check-ignore',p],cwd=ROOT,stdout=subprocess.DEVNULL).returncode==1,p
OUT.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(OUT,'w',zipfile.ZIP_DEFLATED) as z:
 for p in sorted(files):z.write(ROOT/p,p)
with zipfile.ZipFile(OUT) as z:
 assert z.testzip() is None
 assert set(z.namelist())==files
 for p in files:assert z.read(p)==(ROOT/p).read_bytes(),p
print(f'{OUT}: {len(files)} files, {OUT.stat().st_size} bytes; CRC/exact bytes/ignore exceptions verified')
