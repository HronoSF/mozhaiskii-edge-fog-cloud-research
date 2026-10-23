"""Adversarial offline tests; every fixture is synthetic, never a VM experiment."""
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from synthetic_session import build_members, encoded, qualification, verifier, write_fixture


class SessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base=build_members()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='synthetic-public-session-')
        self.addCleanup(self.temp.cleanup)
        self.output=Path(self.temp.name)/'session'
        self.members=copy.deepcopy(self.base)

    def run_fixture(self):
        write_fixture(self.output,self.members)
        return verifier.verify(self.output)

    def mutate_json(self,name,fn):
        value=json.loads(self.members[name]);fn(value);self.members[name]=encoded(value)

    def assert_status(self,report,domain,status):self.assertEqual(report['checks'][domain]['status'],status,report['checks'][domain])

    def test_complete_bounded_checks_not_scientific_eligibility(self):
        r=self.run_fixture();self.assertEqual(r['overall'],'PASS');self.assertEqual(r['performance_eligibility']['status'],'UNVERIFIED')
        self.assertEqual(r['checks']['application']['details']['worker_outputs'],948)
        self.assertEqual(r['checks']['application']['details']['comparison_on_time'],144)

    def test_different_latencies_and_misses_are_allowed(self):
        self.members=build_members(slow=True);r=self.run_fixture()
        self.assert_status(r,'application','PASS');self.assertLess(r['checks']['application']['details']['comparison_on_time'],144)

    def test_missing_source_data(self):
        del self.members['scheduling/cell-00/source/tasks.json'];self.assert_status(self.run_fixture(),'application','UNVERIFIED')

    def test_duplicate_worker_completion(self):
        n='scheduling/cell-00/E/events.jsonl';rows=self.members[n].splitlines();self.members[n]+=rows[-1]+b'\n'
        self.assert_status(self.run_fixture(),'application','FAIL')

    def test_changed_deadline_semantics(self):
        self.mutate_json('scheduling/cell-00/source/tasks.json',lambda rows:rows[0].update(on_time=False))
        self.assert_status(self.run_fixture(),'application','FAIL')

    def test_corrupt_reference_answer(self):
        n='scheduling/cell-00/source/events.jsonl';rows=[json.loads(l) for l in self.members[n].splitlines()]
        next(e for e in rows if e['event']=='validated_result')['message']['value']='AAAA'
        self.members[n]=b''.join(encoded(e) for e in rows);self.assert_status(self.run_fixture(),'application','FAIL')

    def test_wrong_worker(self):
        self.mutate_json('scheduling/cell-00/source/tasks.json',lambda rows:rows[0].update(worker='C'))
        self.assert_status(self.run_fixture(),'application','FAIL')

    def test_incomplete_cycle(self):
        self.mutate_json('scheduling/state.json',lambda s:s['cells'][2].update(status='NOT_EXECUTED'))
        self.assert_status(self.run_fixture(),'application','FAIL')

    def test_failed_calibration(self):
        self.mutate_json('scheduling/calibration-unshaped/source/summary.json',lambda s:s.update(errors=['SYNTHETIC FAILURE']))
        self.assert_status(self.run_fixture(),'application','FAIL')

    def test_missing_calibration(self):
        del self.members['scheduling/calibration-unshaped/source/tasks.json'];self.assert_status(self.run_fixture(),'application','UNVERIFIED')

    def test_changed_profile(self):
        self.mutate_json('scheduling/cell-00/declared-source-config.json',lambda c:c['profiles']['service']['E'].update({'200000:65536':17}))
        self.assert_status(self.run_fixture(),'application','FAIL')

    def test_network_out_of_spec_preserves_application_pass(self):
        _,_,_,gates=verifier.contracts();m,c=qualification('application-qualification',gates,low_rate=True)
        self.members['scheduling/network/measurements.json']=encoded(m)
        self.members['scheduling/network/events.jsonl']=b''.join(encoded(dict(action='acceptance_check',**r)) for r in c)
        r=self.run_fixture();self.assert_status(r,'application','PASS');self.assert_status(r,'network_fidelity','FAIL')
        self.assertEqual(r['checks']['network_fidelity']['details']['network_fidelity'],'OUT_OF_SPEC')

    def test_missing_network_cycle(self):
        self.mutate_json('scheduling/network/measurements.json',lambda m:m.pop())
        self.assert_status(self.run_fixture(),'network_fidelity','FAIL')

    def test_missing_path_counters(self):
        self.mutate_json('scheduling/network/measurements.json',lambda m:m[0].update(path_packet_deltas={}))
        self.assert_status(self.run_fixture(),'network_fidelity','FAIL')

    def test_missing_partition_predicate(self):
        n='scheduling/network/events.jsonl'
        self.members[n]=b''.join(encoded(e) for e in (json.loads(l) for l in self.members[n].splitlines()) if e['description']!='gateway cut/control')
        self.assert_status(self.run_fixture(),'network_fidelity','FAIL')

    def test_dependency_drift(self):
        self.members['python-lock.txt']=b'synthetic-package==9\n';self.assert_status(self.run_fixture(),'environment','FAIL')

    def test_resource_drift(self):
        self.mutate_json('scheduling/cell-05-after-resources.json',lambda m:m['C'].update({'cpu.max':'200000 100000'}))
        self.assert_status(self.run_fixture(),'environment','FAIL')

    def test_cleanup_false(self):
        self.run_fixture();p=self.output/'vm-ledger.json';l=json.loads(p.read_bytes());l['management_port_closed']=False
        p.write_bytes(encoded(l));h=json.loads((self.output/'host-summary.json').read_bytes());h['vm_ledger']=l
        (self.output/'host-summary.json').write_bytes(encoded(h));r=verifier.verify(self.output)
        self.assert_status(r,'application','PASS');self.assert_status(r,'recorded_cleanup','FAIL');self.assertEqual(r['performance_eligibility']['status'],'FAIL')

    def test_cleanup_missing(self):
        self.run_fixture();(self.output/'vm-ledger.json').unlink();r=verifier.verify(self.output)
        self.assert_status(r,'recorded_cleanup','UNVERIFIED');self.assertEqual(r['performance_eligibility']['status'],'UNVERIFIED')

    def test_incomplete_preservation(self):
        self.run_fixture();h=json.loads((self.output/'host-summary.json').read_bytes());h.pop('guest_evidence_sha256')
        (self.output/'host-summary.json').write_bytes(encoded(h));r=verifier.verify(self.output)
        self.assert_status(r,'export_integrity','FAIL');self.assert_status(r,'application','PASS')

    def test_missing_export(self):
        self.run_fixture();(self.output/'guest-evidence.tar.gz').unlink();self.assert_status(verifier.verify(self.output),'export_integrity','UNVERIFIED')

    def test_bad_gzip_crc_even_with_recorded_hash(self):
        self.run_fixture();p=self.output/'guest-evidence.tar.gz';b=bytearray(p.read_bytes());b[-8]^=1;p.write_bytes(b)
        h=json.loads((self.output/'host-summary.json').read_bytes());h['guest_evidence_sha256']=verifier.digest(b)
        (self.output/'host-summary.json').write_bytes(encoded(h));self.assert_status(verifier.verify(self.output),'export_integrity','FAIL')

    def test_traversal_rejected_without_extraction(self):
        self.members['../SYNTHETIC-ESCAPE']=b'x';self.assert_status(self.run_fixture(),'export_integrity','FAIL')
        self.assertFalse((self.output.parent/'SYNTHETIC-ESCAPE').exists())

    def test_duplicate_tar_member(self):
        self.run_fixture();p=self.output/'guest-evidence.tar.gz'
        with tarfile.open(p,'w:gz') as t:
            for _ in range(2):
                m=tarfile.TarInfo('duplicate');m.size=1;t.addfile(m,io.BytesIO(b'x'))
        h=json.loads((self.output/'host-summary.json').read_bytes());h['guest_evidence_sha256']=verifier.digest(p.read_bytes())
        (self.output/'host-summary.json').write_bytes(encoded(h));self.assert_status(verifier.verify(self.output),'export_integrity','FAIL')

    def test_duplicate_json_key(self):
        self.members['scheduling/state.json']=b'{"status":"FAILED","status":"CORRECTNESS_PILOT_COMPLETED"}'
        self.assert_status(self.run_fixture(),'application','FAIL')

    def test_missing_host_summary_is_unverified(self):
        self.run_fixture();(self.output/'host-summary.json').unlink();r=verifier.verify(self.output)
        self.assert_status(r,'recorded_cleanup','UNVERIFIED');self.assertEqual(r['overall'],'UNVERIFIED')

    def test_missing_release_event(self):
        n='scheduling/cell-00/source/events.jsonl';rows=[json.loads(l) for l in self.members[n].splitlines()]
        rows.pop(next(i for i,e in enumerate(rows) if e['event']=='release'))
        self.members[n]=b''.join(encoded(e) for e in rows);self.assert_status(self.run_fixture(),'application','FAIL')

    def test_empty_clock_offsets(self):
        n='scheduling/cell-00/source/events.jsonl';rows=[json.loads(l) for l in self.members[n].splitlines()]
        e=next(e for e in rows if e['event']=='worker_hello');e['source_clock']['offsets']='';e['hello']['clock']['offsets']=''
        self.members[n]=b''.join(encoded(e) for e in rows);self.assert_status(self.run_fixture(),'application','FAIL')

    def test_changed_captured_input(self):
        self.run_fixture();(self.output/'inputs/guest_export.py').write_text('SYNTHETIC TAMPER')
        self.assert_status(verifier.verify(self.output),'source_provenance','FAIL')

    def test_cli_summary_json_and_no_overwrite(self):
        self.run_fixture();result=Path(self.temp.name)/'check.json'
        args=[sys.executable,str(verifier.ROOT/'scripts/verify_session.py'),str(self.output),'--json',str(result)]
        p=subprocess.run(args,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('Scientific performance eligibility: UNVERIFIED',p.stdout)
        self.assertEqual(json.loads(result.read_text())['overall'],'PASS')
        self.assertNotEqual(subprocess.run(args,capture_output=True).returncode,0)


if __name__=='__main__':unittest.main()
