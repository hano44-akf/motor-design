import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from task_store import TaskStore,import_checklist,ROOT
from task_queue import create_plan,run,worker_lock,launch


def mock(ident,depends=(),**payload):
    return {'id':ident,'kind':'mock','payload':{'value':ident,**payload},'depends_on':list(depends),'estimate_s':1,'timeout_s':5}


class TaskQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=TaskStore(Path(self.temp.name)/'tasks.sqlite')
    def tearDown(self):self.temp.cleanup()

    def test_identical_plan_returns_same_job_and_duplicate_inputs_rejected(self):
        tasks=[mock('a'),mock('b',['a'])]
        job=create_plan(self.store,'first',tasks)
        self.assertEqual(create_plan(self.store,'repeated',tasks),job)
        self.assertEqual(len(self.store.list_jobs()),1)
        duplicate=mock('b');duplicate['payload']={'value':'a'}
        with self.assertRaises(ValueError):create_plan(self.store,'duplicate',[mock('a'),duplicate])

    def test_cycles_and_unknown_dependencies_rejected(self):
        for tasks in ([mock('a',['b']),mock('b',['a'])],[mock('a',['missing'])]):
            with self.assertRaises(ValueError):create_plan(self.store,'bad',tasks)

    def test_failure_blocks_dependent_retry_preserves_completed_artifacts(self):
        tasks=[mock('a'),mock('b',['a'],fail_until_attempt=1),mock('c',['b'])]
        job=create_plan(self.store,'retry',tasks)
        first=run(self.store,job)
        self.assertEqual(first['counts'],{'completed':1,'failed':1,'blocked':1})
        old=first['tasks'][0]['output'];self.assertTrue(Path(old['result_file']).is_file())
        second=run(self.store,job,resume=True,retry_ids=['b'])
        self.assertEqual(second['state'],'completed')
        self.assertEqual([t['attempts'] for t in second['tasks']],[1,2,1])
        self.assertEqual(second['tasks'][0]['output'],old)
        self.assertEqual([a['state'] for a in second['attempts']].count('failed'),1)
        self.assertEqual(run(self.store,job)['attempts'],second['attempts'])

    def test_stop_then_resume_does_not_repeat_completed_task(self):
        job=create_plan(self.store,'stop',[mock('a',duration_s=.4),mock('b',['a'])])
        errors=[]
        def worker():
            try:run(self.store,job)
            except BaseException as exc:errors.append(exc)
        thread=threading.Thread(target=worker);thread.start()
        deadline=time.monotonic()+5
        while self.store.snapshot(job)['tasks'][0]['state']!='running':
            if time.monotonic()>deadline:self.fail('Worker did not start')
            time.sleep(.02)
        self.store.set_stop(job);thread.join(timeout=10)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
        self.assertEqual(self.store.snapshot(job)['state'],'stopped')
        final=run(self.store,job,resume=True)
        self.assertEqual(final['state'],'completed');self.assertEqual([t['attempts'] for t in final['tasks']],[1,1])

    def test_second_worker_cannot_claim_work(self):
        job=create_plan(self.store,'lock',[mock('a')])
        with worker_lock(self.store.path):
            with self.assertRaises(ValueError):run(self.store,job)
        self.assertEqual(self.store.snapshot(job)['tasks'][0]['attempts'],0)

    def test_native_is_blocked_by_default(self):
        # Store-level synthetic native task is not dispatched and cannot import
        # or start an actual application without allow_native.
        job=self.store.create('native',[{'id':'n','kind':'motorcad_verify','payload':{}}])
        result=run(self.store,job)
        self.assertEqual(result['state'],'blocked');self.assertEqual(result['tasks'][0]['reason'],'native_execution_not_enabled')
        self.assertEqual(result['attempts'],[])

    def test_interrupted_worker_requires_review_before_retry(self):
        job=create_plan(self.store,'interrupted',[mock('a')])
        self.store.begin_worker(job);task=self.store.claim(job)
        self.store.begin_worker(job)
        state=self.store.snapshot(job)
        self.assertEqual(state['tasks'][0]['reason'],'interrupted_worker_review_required')
        with self.assertRaises(ValueError):self.store.retry(job,'a')
        self.assertTrue(Path(task['output_dir']).is_dir())

    def test_recipe_less_checklist_is_not_executable(self):
        job=import_checklist(self.store,ROOT/'outputs/topology_optimization_20261027/validation_queue.json')
        result=run(self.store,job)
        self.assertEqual(result['total_tasks'],88);self.assertEqual(result['counts'],{'blocked':88})
        self.assertIsNone(result['estimated_remaining_s']);self.assertEqual(result['attempts'],[])

    def test_timeout_has_attempt_history_and_no_result(self):
        task=mock('a',duration_s=2);task['timeout_s']=.1
        job=create_plan(self.store,'timeout',[task]);result=run(self.store,job)
        self.assertEqual(result['tasks'][0]['state'],'failed')
        self.assertIn('timeout',result['tasks'][0]['error'])
        self.assertTrue(Path(result['attempts'][0]['output_dir'],'worker.log').is_file())

    def test_artifact_ids_cannot_escape_folder(self):
        for ident in ('../bad','..','a/b','a:b'):
            with self.assertRaises(ValueError):create_plan(self.store,'bad',[mock(ident)])

    def test_native_recipe_rejects_source_geometry_change_before_launch(self):
        f=json.loads((ROOT/'validation/jobs/20261022_165707/result.json').read_text(encoding='utf-8'))
        request=f['request'];request.update(formula_source_job='20261022_165707',selected_model_ids=['A'])
        request['bounds'][0]=[60,90]
        with self.assertRaisesRegex(ValueError,'mismatch'):
            create_plan(self.store,'native',[{'id':'verify','kind':'motorcad_verify','payload':{'request':request}}])

    def test_changed_input_file_is_not_reused_or_silently_retried(self):
        root=Path(self.temp.name);source=root/'source.json';source.write_text('before')
        with patch('task_store.ROOT',root):
            spec=mock('a');spec['input_files']=[str(source)]
            job=self.store.create('hash',[spec]);source.write_text('after')
            result=run(self.store,job)
            self.assertEqual(result['tasks'][0]['reason'],'input_changed');self.assertEqual(result['attempts'],[])
            with self.assertRaises(ValueError):self.store.retry(job,'a',True)

    def test_version_drift_is_rejected_before_execution(self):
        job=create_plan(self.store,'version',[mock('a')])
        with patch('task_store.implementation_digest',return_value='changed'):
            with self.assertRaisesRegex(ValueError,'Implementation changed'):run(self.store,job)
        self.assertEqual(self.store.snapshot(job)['attempts'],[])

    def test_changed_completed_artifact_is_reported_and_preserved(self):
        job=create_plan(self.store,'artifact',[mock('a')]);first=run(self.store,job)
        file=Path(first['tasks'][0]['output']['result_file']);file.write_text('changed')
        result=run(self.store,job)
        self.assertEqual(result['tasks'][0]['reason'],'completed_artifact_changed')
        self.assertEqual(result['tasks'][0]['attempts'],1)
        with self.assertRaises(ValueError):self.store.retry(job,'a')
        self.assertEqual(file.read_text(),'changed')

    def test_uncertain_native_failure_blocks_other_native_work(self):
        job=self.store.create('native',[{'id':'a','kind':'motorcad_verify','payload':{'model':'a'}},
                                        {'id':'b','kind':'motorcad_verify','payload':{'model':'b'}}])
        self.store.begin_worker(job);a=self.store.claim(job,True)
        self.store.finish(job,'a',a['attempt'],error='simulated interrupted native call')
        self.assertIsNone(self.store.claim(job,True))
        self.assertEqual(self.store.snapshot(job)['tasks'][1]['reason'],'prior_native_failure_review_required')

    def test_formula_adapter_executes_without_any_native_work(self):
        r=json.loads((ROOT/'validation/jobs/20261022_165707/result.json').read_text(encoding='utf-8'))['request']
        r['bounds']=[[85,85],[20,20],[6,6],[1.8,1.8]];r['airgap_bounds_mm']=[.5,.5]
        job=create_plan(self.store,'formula',[{'id':'f','kind':'formula','payload':{'request':r},'timeout_s':30}])
        result=run(self.store,job);self.assertEqual(result['state'],'completed')
        saved=json.loads(Path(result['tasks'][0]['output']['result_file']).read_text(encoding='utf-8'))
        self.assertEqual(saved['search_statistics']['motorcad_solves'],0)

    def test_artifact_access_is_scoped_to_task_attempt_and_allowlist(self):
        job=create_plan(self.store,'artifact access',[mock('a')]);result=run(self.store,job)
        file=self.store.artifact(job,'a',1,'result.json');self.assertTrue(file.is_file())
        self.assertEqual(str(file),result['tasks'][0]['output']['result_file'])
        for task,attempt,name in [('a',1,'../tasks.sqlite'),('a',2,'result.json'),('missing',1,'worker.log')]:
            with self.assertRaises(ValueError):self.store.artifact(job,task,attempt,name)

    def test_launch_rejects_version_drift_before_detaching(self):
        job=create_plan(self.store,'version',[mock('a')])
        with patch('task_store.implementation_digest',return_value='changed'),patch('task_queue.subprocess.Popen',side_effect=AssertionError('Must not launch')):
            with self.assertRaisesRegex(ValueError,'Implementation changed'):launch(self.store,job)


if __name__=='__main__':unittest.main()
