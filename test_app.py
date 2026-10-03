import argparse, copy, json, subprocess, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import app
from engine import ROOT


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.c=json.loads((ROOT/'runs/revised/candidate.json').read_text())
        self.mutant=json.loads((ROOT/'runs/demo/case-07/candidate.json').read_text())
        self.bad_review=json.loads((ROOT/'runs/demo/case-07/review.json').read_text())
        self.good_review=dict(candidate_name=self.c['name'],findings=[],unresolved_questions=[],summary='No objections')

    def test_transport_disconnects_connectors_and_parses_structured_output(self):
        events='\n'.join(json.dumps(x) for x in [
            {'type':'item.completed','item':{'type':'agent_message','text':json.dumps(self.c)}},
            {'type':'turn.completed','usage':{'input_tokens':12,'output_tokens':20}}])
        def fake(command,**kwargs):
            if 'list' in command and 'mcp' in command:
                self.assertIn('plugins',command)
                self.assertIn('apps',command)
                return subprocess.CompletedProcess(command,0,stdout='[{"name":"test-connector"}]',stderr='')
            self.assertIn('--ephemeral',command)
            self.assertIn('read-only',command)
            self.assertIn('mcp_servers.test-connector.enabled=false',command)
            self.assertIn('shell_tool',command)
            self.assertIn('apps',command)
            self.assertIn('plugins',command)
            self.assertEqual(command[-1],'-')
            self.assertIn('Do not browse',kwargs['input'])
            return subprocess.CompletedProcess(command,0,stdout=events,stderr='')
        with tempfile.TemporaryDirectory() as d,patch('app.shutil.which',return_value='/mock/codex'),patch('app.subprocess.run',side_effect=fake):
            result=app.invoke_agent('proposer',{'intent':app.INTENT},d,30)
            self.assertEqual(result,self.c)
            self.assertEqual(json.loads((Path(d)/'usage.json').read_text())['usage']['output_tokens'],20)

    def test_transport_rejects_ambiguous_connector_override(self):
        listing=subprocess.CompletedProcess([],0,stdout='[{"name":"unsafe.name"}]',stderr='')
        with tempfile.TemporaryDirectory() as d,patch('app.shutil.which',return_value='/mock/codex'),patch('app.subprocess.run',return_value=listing) as process:
            with self.assertRaisesRegex(RuntimeError,'Connector name'):
                app.invoke_agent('reviewer',{'intent':app.INTENT},d,30)
            self.assertEqual(process.call_count,1)

    def test_repair_orchestration_with_recorded_response_stubs(self):
        # This validates transport/control flow; it is NOT a live AI repair run.
        with tempfile.TemporaryDirectory() as d,patch('app.invoke_agent',side_effect=[self.bad_review,self.c,self.good_review]) as transport:
            args=argparse.Namespace(output=str(Path(d)/'run'),candidate=str(ROOT/'runs/demo/case-07/candidate.json'),rounds=2,timeout=30,skip_lean=True)
            app.agents(args)
            self.assertEqual([c.args[0] for c in transport.call_args_list],['reviewer','proposer','reviewer'])
            payload=json.loads((Path(args.output)/'report.json').read_text())
            self.assertEqual(len(payload['cases']),2)
            self.assertEqual(payload['cases'][0]['evaluation']['validated_findings'],1)
            self.assertEqual(payload['cases'][1]['evaluation']['validated_findings'],0)
            self.assertFalse(payload['accepted'])

    def test_false_criticism_stops_automatic_repair(self):
        review=copy.deepcopy(self.good_review)
        review['findings']=[dict(requirement_id='R3',explanation='unsupported',trace=[
            dict(kind='fund',caller='alice',time=0,amount=100,transfer_ok=True),
            dict(kind='release',caller='eve',time=10,amount=0,transfer_ok=True)])]
        with tempfile.TemporaryDirectory() as d,patch('app.invoke_agent',return_value=review) as transport:
            args=argparse.Namespace(output=str(Path(d)/'run'),candidate=str(ROOT/'runs/revised/candidate.json'),rounds=2,timeout=30,skip_lean=True)
            app.agents(args)
            self.assertEqual(transport.call_count,1)

    def test_report_escapes_untrusted_embedded_data(self):
        c=copy.deepcopy(self.c); c['name']='</script><img src=x onerror=alert(1)>'
        with tempfile.TemporaryDirectory() as d:
            app.report(d,[{'candidate':c}],{'test':'local'})
            html=(Path(d)/'report.html').read_text()
            self.assertNotIn(c['name'],html)
            self.assertIn('\\u003c/script\\u003e',html)


if __name__=='__main__': unittest.main()
