"""Release controls use offline Docker doubles; never claim native acceptance."""
import copy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.pgv13release import release as R


def manifest():
    return {'schema_version':'pgv13.release/1','state':'BUILT','revision':'a'*40,'tree':'b'*40,
            'release_id':'c'*12,'images':{'api':'sha256:'+'1'*64,'web':'sha256:'+'2'*64,'print-renderer':'sha256:'+'3'*64},
            'profile_sha256':R.digest(R.PROFILE.read_bytes()),
            'volume':'cisstat_renderer_ipc_cccccccccccc',
            'candidate_volume':'cisstat_renderer_ipc_cccccccccccc_candidate',
            'candidate_project':'cisstat-pgv13-cccccccccccc-candidate'}


class ReleaseTests(unittest.TestCase):
    def test_descriptor_requires_three_immutable_images_one_source(self):
        m=manifest();R.validate_manifest(m)
        for change in [lambda x:x.update(state='BUILDING'),lambda x:x.update(revision='unverified'),
                       lambda x:x['images'].update(api='api:latest'),lambda x:x['images'].pop('web'),
                       lambda x:x.update(volume='science_data'),lambda x:x.update(candidate_volume=x['volume'])]:
            bad=copy.deepcopy(m);change(bad)
            with self.assertRaises(ValueError):R.validate_manifest(bad)

    def test_all_dockerfiles_stamp_final_runtime_revision_and_tree(self):
        for name in R.DOCKERFILES.values():
            text=(R.ROOT/name).read_text(encoding='utf-8')
            runtime=text[text.rfind('\nFROM '):]
            for token in ['ARG CISSTAT_SOURCE_REVISION','ARG CISSTAT_SOURCE_TREE',
                          'org.opencontainers.image.revision','io.cisstat.source-tree',
                          '/usr/local/share/cisstat/build.json']:
                self.assertIn(token,runtime,name)

    def test_labels_and_inside_image_marker_must_match_descriptor(self):
        m=manifest()
        meta={'id':m['images']['api'],'revision':m['revision'],'tree':m['tree']}
        R.validate_image(meta,m,'api')
        for key,value in [('id',m['images']['web']),('revision','0'*40),('tree','0'*40)]:
            wrong={**meta,key:value}
            with self.assertRaises(ValueError):R.validate_image(wrong,m,'api')

    def test_generated_configs_keep_ipc_hardening_and_all_three_ids(self):
        m=manifest()
        stack,renderer=R.models(m,Path('/release/seccomp.json'),False)
        R.validate_models(m,stack,renderer,Path('/release/seccomp.json'))
        for change in [lambda s,r:s['services']['api']['volumes'][0].update(read_only=False),
                       lambda s,r:r['services']['print-renderer'].update(network_mode='host'),
                       lambda s,r:r['services']['print-renderer'].update(pids_limit=128),
                       lambda s,r:r['services']['print-renderer'].update(cap_add=['SYS_ADMIN']),
                       lambda s,r:r['services']['print-renderer'].update(volumes=[]),
                       lambda s,r:s['services']['web'].update(image='web:latest')]:
            s,r=copy.deepcopy(stack),copy.deepcopy(renderer);change(s,r)
            with self.assertRaises(ValueError):R.validate_models(m,s,r,Path('/release/seccomp.json'))

    def test_candidate_and_production_use_distinct_private_volumes(self):
        m=manifest();_,prod=R.models(m,Path('/p'),False);_,candidate=R.models(m,Path('/p'),True)
        self.assertNotEqual(prod['volumes']['renderer_ipc']['name'],candidate['volumes']['renderer_ipc']['name'])

    def test_new_ab_is_pinned_to_new_image_revision_tree_and_capacity(self):
        m=manifest()
        ab={'image_id':m['images']['print-renderer'],'source_revision':m['revision'],
            'source_tree':m['tree'],'pids_limit':512,'rows':[{'probe':{'limits':{'pids_max':512,'memory_max':2147483648}}}]*4}
        native={'passed':True,'pgv13_certified':False,'mode':'candidate-api-image',
                'image_id':ab['image_id'],'api_image_id':m['images']['api'],
                'volume':m['candidate_volume'],'recreate_verified':True}
        with patch.object(R,'validate_ab',return_value=ab['image_id']),patch.object(R,'validate_native'):
            R.validate_evidence(m,ab,native)
            for key,value in [('image_id','sha256:'+'0'*64),('source_revision','0'*40),
                              ('source_tree','0'*40),('pids_limit',128)]:
                wrong={**ab,key:value}
                with self.assertRaises(ValueError):R.validate_evidence(m,wrong,native)
            for key,value in [('api_image_id','sha256:'+'0'*64),('volume',m['volume']),
                              ('recreate_verified',False),('passed',False)]:
                with self.assertRaises(ValueError):R.validate_evidence(m,ab,{**native,key:value})

    def test_baseline_snapshot_removes_platform_secrets_and_preserves_uds(self):
        m=manifest();stack,renderer=R.models(m,Path('/p'),False)
        stack['services']['api']['environment']['DATABASE_URL']='DO-NOT-SAVE-DB-SECRET'
        saved=R.safe_baseline(stack,renderer,m['images'],{'api':{},'web':{},'print-renderer':{}})
        self.assertNotIn('DO-NOT-SAVE',json.dumps(saved))
        self.assertEqual(saved['stack']['services']['api']['environment']['CISSTAT_PNG_RENDERER_IPC'],R.SOCKET)
        self.assertEqual(saved['renderer']['services']['print-renderer']['volumes'],renderer['services']['print-renderer']['volumes'])
        self.assertEqual(saved['renderer']['services']['print-renderer']['pids_limit'],512)

    def test_rollback_preserves_legacy_baseline_instead_of_inventing_ipc(self):
        m=manifest();stack,renderer=R.models(m,Path('/p'),False)
        stack['services']['api']['environment']={};stack['services']['api']['volumes']=[]
        renderer['services']['print-renderer']['environment'].pop('CISSTAT_PRINT_RENDERER_SOCKET')
        renderer['services']['print-renderer']['volumes']=[];renderer['volumes']={}
        renderer['services']['print-renderer']['pids_limit']=128
        saved=R.safe_baseline(stack,renderer,m['images'],{'api':{},'web':{},'print-renderer':{}})
        self.assertEqual(saved['transport'],'legacy')
        self.assertEqual(saved['renderer']['services']['print-renderer']['volumes'],[])
        self.assertEqual(saved['renderer']['services']['print-renderer']['pids_limit'],128)

    def test_stale_baseline_never_overwrites_an_unrelated_deployment(self):
        m=manifest();old={k:'sha256:'+'9'*64 for k in m['images']}
        R.validate_current(m,old,old,False)
        R.validate_current(m,old,{**old,'api':m['images']['api']},True)
        with self.assertRaises(ValueError):R.validate_current(m,old,{**old,'api':'sha256:'+'8'*64},True)
        with self.assertRaises(ValueError):R.validate_current(m,old,{**old,'api':m['images']['api']},False)

    def test_partial_switch_missing_service_requires_own_operation_journal(self):
        m=manifest();old={k:'sha256:'+'9'*64 for k in m['images']};partial={**old,'web':None}
        with self.assertRaises(ValueError):R.validate_current(m,old,partial,True)
        R.validate_current(m,old,partial,True,True)

    def test_dirty_build_stops_before_docker_without_claiming_built(self):
        with tempfile.TemporaryDirectory(dir=R.ROOT.parent) as d:
            bundle=Path(d)/'release'
            args=type('Args',(),{'bundle':bundle})()
            with patch.object(R,'command',return_value=' M source.py') as cmd:
                with self.assertRaises(ValueError):R.build(args)
            self.assertEqual(cmd.call_count,1)
            self.assertEqual(json.loads((bundle/'manifest.json').read_text())['state'],'BUILDING')

    def test_switch_order_and_failure_keep_an_explicit_partial_operation(self):
        m=manifest()
        old={'stack_project':'stack','renderer_project':'renderer',
             'stack_files':['base-stack.yml'],'images':{k:'sha256:'+'9'*64 for k in R.ROLES}}
        with tempfile.TemporaryDirectory() as d:
            args=type('Args',(),{'bundle':Path(d)})()
            calls=[]
            def execute(argv,**kw):
                calls.append(argv)
                if 'up' in argv:raise ValueError('controlled up failure')
                return ''
            with patch.object(R,'bundle_load',return_value=(Path(d),m)),patch.object(R,'load_baseline',return_value=old),patch.object(R,'command',side_effect=execute):
                with self.assertRaises(ValueError):R.switch(args)
            self.assertEqual(calls[0][-3:],['stop','web','api'])
            self.assertEqual(calls[1][-1],'print-renderer')
            self.assertIn('--no-build',calls[1]);self.assertIn('never',calls[1])
            self.assertFalse(any('down' in c or 'rm' in c for c in calls))
            state=json.loads((Path(d)/'operation.json').read_text())
            self.assertTrue(state['mutation_started'] and state['failed'])
            self.assertEqual(state['phase'],'renderer')

    def test_explicit_ab_uses_new_image_without_querying_running_renderer(self):
        from scripts.pgv13sandbox import probe as P
        m=manifest();seen=[]
        def metadata(args):
            self.assertEqual(args[:2],['image','inspect'])
            return json.dumps({'id':m['images']['print-renderer'],'revision':m['revision'],'tree':m['tree']})
        def arm(name,image,path,**kwargs):
            seen.append(name);self.assertEqual(image,m['images']['print-renderer']);self.assertEqual(kwargs['pids_limit'],512)
            ok=name=='namespaces-chroot'
            return {'arm':name,'exit':0 if ok else 1,'probe':{'isolation_ok':True,'launch_verified':True,'smoke':{'verdict':'passed' if ok else 'failed','error':None},'limits':{'pids_max':512,'memory_max':2147483648}}}
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'ab.json'
            with patch.object(P,'docker_value',side_effect=metadata),patch.object(P,'run_arm',side_effect=arm),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(P.main(['--image',m['images']['print-renderer'],'--expected-revision',m['revision'],'--expected-tree',m['tree'],'--pids-limit','512','--with-chroot','--out',str(out)]),0)
            report=json.loads(out.read_text());self.assertEqual(report['source_revision'],m['revision']);self.assertEqual(report['source_tree'],m['tree'])
            self.assertEqual(seen,['builtin','reference','namespaces','namespaces-chroot'])

    def test_explicit_ab_wrong_labels_invalidate_stale_report_before_arms(self):
        from scripts.pgv13sandbox import probe as P
        m=manifest()
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'ab.json';out.write_text('{"conclusion":"CHROOT_RULE_CANDIDATE"}')
            with patch.object(P,'docker_value',return_value=json.dumps({'id':m['images']['print-renderer'],'revision':'0'*40,'tree':m['tree']})),patch.object(P,'run_arm') as arm,contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(P.main(['--image',m['images']['print-renderer'],'--expected-revision',m['revision'],'--expected-tree',m['tree'],'--with-chroot','--out',str(out)]),2)
            arm.assert_not_called();self.assertEqual(json.loads(out.read_text())['conclusion'],'INCONCLUSIVE_SETUP')

    def test_readonly_check_never_recreates_or_stops_services(self):
        with patch.object(R,'preflight',return_value={'passed':True}),patch.object(R,'switch') as switch:
            with tempfile.TemporaryDirectory() as d:
                self.assertEqual(R.main(['check','--bundle',d,'--ab-report','ab.json','--native-report','native.json']),0)
        switch.assert_not_called()

    def test_apply_and_rollback_require_explicit_quiesced_assertion(self):
        for action in ['apply','rollback']:
            with patch.object(R,'preflight') as preflight,patch.object(R,'switch') as switch:
                with tempfile.TemporaryDirectory() as d:
                    self.assertEqual(R.main([action,'--bundle',d]),2)
            preflight.assert_not_called();switch.assert_not_called()


if __name__=='__main__':unittest.main()
