"""Actual pipe-drain regression tests using trusted literal Python programs."""
import sys
from worker_runtime import bounded_process


def test_bounded_process_reads_both_streams():
    result=bounded_process([sys.executable,'-c','import sys;print(42);print("diagnostic",file=sys.stderr)'])
    assert result['status']=='completed' and result['stdout']=='42\n' and result['stderr']=='diagnostic\n'


def test_output_flood_is_stopped_before_unbounded_capture():
    result=bounded_process([sys.executable,'-c','import sys\nwhile True: sys.stdout.write("x"*32768);sys.stdout.flush()'],output_limit=65536)
    assert result['status']=='failed' and result['exit_code']==125
    assert result['reason']=='Execution output limit exceeded' and len(result['stdout'])<=24000


def test_silent_process_respects_deadline():
    result=bounded_process([sys.executable,'-c','import time;time.sleep(20)'],timeout=.05)
    assert result['status']=='failed' and result['exit_code']==124
