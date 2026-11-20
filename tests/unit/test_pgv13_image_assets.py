"""Image data packaging regression. Projection is not a Docker build claim."""
import importlib.util
import json
from pathlib import Path
import shlex
import shutil
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
ASSETS=('config/print_schema.json','config/visual_registry.json')


def project_runtime(root,recipe=None):
    """Project required COPY inputs from the actual single-stage API recipe.

    Only the stdlib schema reader and its two data assets are needed to
    reproduce this failure; scientific dependencies are not simulated.
    """
    destination=root/'apps/api'
    destination.mkdir(parents=True)
    shutil.copyfile(ROOT/'apps/api/print_schema.py',destination/'print_schema.py')
    recipe=(recipe if recipe is not None else (ROOT/'apps/api/Dockerfile').read_text()).replace('\\\n',' ')
    for line in recipe.splitlines():
        if not line.startswith('COPY '):
            continue
        args=shlex.split(line[5:])
        if any(a.startswith('--from=') for a in args):
            continue
        args=[a for a in args if not a.startswith('--')]
        for source in args[:-1]:
            for name in ASSETS:
                if source.rstrip('/')=='config' or source.lstrip('./')==name:
                    target=root/args[-1].lstrip('./')
                    if args[-1].endswith('/') or len(args)>2 or (ROOT/source).is_dir():
                        target=target/Path(name).name
                    target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(ROOT/name,target)
    spec=importlib.util.spec_from_file_location('pgv13_projected_schema',destination/'print_schema.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ImageAssetTests(unittest.TestCase):
    def test_previous_recipe_reproduces_exact_missing_schema_path(self):
        recipe=(ROOT/'apps/api/Dockerfile').read_text().replace('COPY config/print_schema.json config/visual_registry.json ./config/','')
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as temp:
            schema=project_runtime(Path(temp),recipe)
            with self.assertRaises(FileNotFoundError) as caught:
                schema.resolve_print_profile('figure-landscape')
            self.assertEqual(Path(caught.exception.filename),Path(temp)/'config/print_schema.json')
    def test_actual_api_recipe_ships_readable_profile_and_registry_twins(self):
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as temp:
            schema=project_runtime(Path(temp))
            profiles=schema.load_print_schema()['profiles']
            self.assertEqual({p['id'] for p in profiles},{'figure-landscape','a4-landscape','a4-portrait'})
            self.assertTrue(all(schema.profile_pixel_consistency(p) for p in profiles))
            self.assertEqual(schema.load_visual_registry()['schema_version'],'pgv.visual_registry/1')
            for name in ASSETS:
                self.assertEqual((Path(temp)/name).read_bytes(),(ROOT/name).read_bytes())

    def test_final_image_build_guard_reads_data_before_revision_stamp(self):
        recipe=(ROOT/'apps/api/Dockerfile').read_text()
        copy=recipe.index('COPY config/print_schema.json config/visual_registry.json ./config/')
        guard=recipe.index('load_print_schema, load_visual_registry, profile_pixel_consistency',copy)
        stamp=recipe.index('ARG CISSTAT_SOURCE_REVISION')
        self.assertLess(copy,guard)
        self.assertLess(guard,stamp)
        # Data guard is a final runtime check, before provenance stamping.
        self.assertGreater(copy,recipe.index('psycopg + full API startup OK'))

    def test_asset_preflight_rejects_missing_image_file(self):
        from scripts.pgv13accept import verify_vm as V
        with patch.object(V,'command',return_value=json.dumps({'files':{}})):
            with self.assertRaisesRegex(ValueError,'asset|print'):
                V.verify_api_print_assets('sha256:'+'a'*64)

    def test_asset_preflight_rejects_modified_image_data(self):
        from scripts.pgv13accept import verify_vm as V
        result={'files':{name:{'present':True,'sha256':'0'*64} for name in ASSETS},'catalogs_valid':True}
        with patch.object(V,'command',return_value=json.dumps(result)):
            with self.assertRaisesRegex(ValueError,'asset|print'):
                V.verify_api_print_assets('sha256:'+'a'*64)

    def test_asset_preflight_accepts_only_actual_matching_bytes(self):
        from scripts.pgv13accept import verify_vm as V
        result={'files':{name:{'present':True,'sha256':V.O.sha((ROOT/name).read_bytes().replace(b'\r\n',b'\n'))} for name in ASSETS},'catalogs_valid':True}
        with patch.object(V,'command',return_value=json.dumps(result)) as command:
            self.assertEqual(V.verify_api_print_assets('sha256:'+'a'*64),result)
            args=command.call_args.args[0]
            self.assertIn('--network=none',args)
            self.assertIn('--read-only',args)
            self.assertIn('--pull=never',args)

    def test_invalid_catalog_flag_is_not_accepted_with_matching_hashes(self):
        from scripts.pgv13accept import verify_vm as V
        result={'files':{name:{'present':True,'sha256':V.O.sha((ROOT/name).read_bytes().replace(b'\r\n',b'\n'))} for name in ASSETS},'catalogs_valid':False}
        with patch.object(V,'command',return_value=json.dumps(result)):
            with self.assertRaisesRegex(ValueError,'catalog'):
                V.verify_api_print_assets('sha256:'+'a'*64)

    def test_actual_build_guard_and_image_probe_execute_in_projected_runtime(self):
        from scripts.pgv13accept import verify_vm as V
        recipe=(ROOT/'apps/api/Dockerfile').read_text().replace('\\\n',' ')
        guard=re.search(r'RUN python -c "(from apps.api.print_schema import load_print_schema, load_visual_registry, profile_pixel_consistency;.*?)"\nARG CISSTAT_SOURCE_REVISION',recipe).group(1)
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as temp:
            project_runtime(Path(temp))
            env=dict(os.environ,PYTHONPATH=temp)
            built=subprocess.run([sys.executable,'-c',guard],cwd=temp,env=env,capture_output=True,text=True)
            self.assertEqual(built.returncode,0,built.stderr)
            probed=subprocess.run([sys.executable,'-c',V.API_PRINT_ASSETS],cwd=temp,env=env,capture_output=True,text=True)
            self.assertEqual(probed.returncode,0,probed.stderr)
            self.assertTrue(json.loads(probed.stdout)['catalogs_valid'])
            (Path(temp)/'config/print_schema.json').unlink()
            broken=subprocess.run([sys.executable,'-c',guard],cwd=temp,env=env,capture_output=True,text=True)
            self.assertNotEqual(broken.returncode,0)
            self.assertIn('FileNotFoundError',broken.stderr)

    def test_both_assets_are_bound_to_native_client_source_check(self):
        from scripts.pgv13accept import verify_vm as V
        sources=V.product_sources('3b13214466a31fb9ceeebe583abd64812e3bd042')
        self.assertTrue(set(ASSETS)<=set(sources))

    def test_corrupt_catalog_never_becomes_an_empty_fallback(self):
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as temp:
            schema=project_runtime(Path(temp))
            path=Path(temp)/'config/visual_registry.json'
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text('{broken')
            with self.assertRaises(json.JSONDecodeError):
                schema.load_visual_registry()


if __name__=='__main__':
    unittest.main()
