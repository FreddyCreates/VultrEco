"""File-capable disposable Docker task execution on a separate worker VM."""
import base64,binascii,hashlib,os,pathlib,re,subprocess,tempfile,uuid

MAX_INPUT_FILES=12
MAX_INPUT_TOTAL=384000
MAX_OUTPUT_FILES=16
MAX_OUTPUT_TOTAL=768000
MAX_FILE=256000
PATH=re.compile(r'^[A-Za-z0-9][A-Za-z0-9._/-]{0,119}$')
IMAGE=re.compile(r'^[A-Za-z0-9][A-Za-z0-9._/:@-]{1,127}$')

def safe_name(path):
    return (isinstance(path,str) and bool(PATH.fullmatch(path)) and
            all(part not in ('','.','..') and not part.startswith('.') for part in path.split('/')))

def decode_inputs(inputs):
    if not isinstance(inputs,dict) or len(inputs)>MAX_INPUT_FILES:
        raise ValueError('Too many input files')
    decoded={};total=0
    for path,encoded in inputs.items():
        if not safe_name(path) or not isinstance(encoded,str):
            raise ValueError('Unsafe input file path')
        try:value=base64.b64decode(encoded,validate=True)
        except (ValueError,binascii.Error) as exc:raise ValueError('Invalid input encoding') from exc
        total+=len(value)
        if len(value)>MAX_FILE or total>MAX_INPUT_TOTAL:raise ValueError('Input payload exceeds limits')
        decoded[path]=value
    return decoded

def collect_outputs(root):
    files={};total=0
    for directory,subdirs,names in os.walk(root,followlinks=False):
        if any((pathlib.Path(directory)/part).is_symlink() for part in subdirs):
            raise ValueError('Symlink output directory forbidden')
        for name in names:
            path=pathlib.Path(directory)/name
            relative=path.relative_to(root).as_posix()
            if not safe_name(relative) or path.is_symlink() or not path.is_file():
                raise ValueError('Unsafe output')
            if len(files)>=MAX_OUTPUT_FILES:raise ValueError('Output count exceeded')
            size=path.stat().st_size
            total+=size
            if size>MAX_FILE or total>MAX_OUTPUT_TOTAL:raise ValueError('Output size exceeded')
            handle=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
            with os.fdopen(handle,'rb') as f:data=f.read(MAX_FILE+1)
            if len(data)!=size:raise ValueError('Output mutated')
            files[relative]={'base64':base64.b64encode(data).decode('ascii'),
                             'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
    return dict(sorted(files.items()))

def execute_capsule(code,inputs,*,bounded_process,run=None,env=None):
    env=env or os.environ
    if not isinstance(code,str) or not code.strip() or len(code)>16000:
        return {'status':'denied','reason':'Bounded code required','artifacts':{},'cleanup':'not-started'}
    try:decoded=decode_inputs(inputs)
    except ValueError as exc:
        return {'status':'denied','reason':str(exc),'artifacts':{},'cleanup':'not-started'}
    host_root=env.get('CAPSULA_WORKER_HOST_RUN_PATH','')
    container_root=env.get('CAPSULA_WORKER_CONTAINER_RUN_PATH','/work/runs')
    image=env.get('CAPSULA_WORKER_SANDBOX_IMAGE','python:3.12-alpine')
    if (not host_root or not pathlib.Path(host_root).is_absolute()
            or not pathlib.Path(container_root).is_dir() or not IMAGE.fullmatch(image)):
        return {'status':'denied','reason':'Disposable Docker worker unavailable',
                'artifacts':{},'cleanup':'not-started'}
    runner=run or subprocess.run
    with tempfile.TemporaryDirectory(prefix='capsula-job-',dir=container_root) as scratch:
        base=pathlib.Path(scratch);base.chmod(0o711)
        task=base/'task.py';task.write_text(code,encoding='utf-8');task.chmod(0o644)
        inp=base/'inputs';inp.mkdir(mode=0o755)
        output=base/'outputs';output.mkdir(mode=0o777)
        for relative,data in decoded.items():
            dest=inp/relative;dest.parent.mkdir(parents=True,exist_ok=True)
            dest.parent.chmod(0o755);dest.write_bytes(data);dest.chmod(0o644)
        host=pathlib.Path(host_root)/base.name
        name='capsula-job-'+uuid.uuid4().hex[:20]
        cmd=['docker','run','--rm','--name',name,'--network','none','--read-only',
             '--cap-drop','ALL','--security-opt','no-new-privileges',
             '--pids-limit','64','--memory','256m','--memory-swap','256m',
             '--cpus','1','--user','65534:65534',
             '--tmpfs','/tmp:rw,noexec,nosuid,size=24m',
             '--mount',f'type=bind,src={host}/task.py,dst=/task.py,readonly',
             '--mount',f'type=bind,src={host}/inputs,dst=/inputs,readonly',
             '--mount',f'type=bind,src={host}/outputs,dst=/outputs',
             '--workdir','/outputs',image,'python','-B','/task.py']
        try:
            result=bounded_process(cmd,timeout=30,output_limit=256000)
        except (OSError,subprocess.TimeoutExpired):
            result={'status':'failed','reason':'Isolated executor unavailable',
                    'stdout':'','stderr':'','exit_code':None}
        finally:
            try:
                runner(['docker','rm','-f',name],capture_output=True,timeout=8,check=False)
                inspected=runner(['docker','container','inspect',name],capture_output=True,timeout=8,check=False)
                cleanup='verified-destroyed' if inspected.returncode!=0 else 'not-verified'
            except (OSError,subprocess.TimeoutExpired):cleanup='not-verified'
        if cleanup!='verified-destroyed':
            return {'status':'failed','reason':'Container removal not verified',
                    'cleanup':cleanup,'artifacts':{},'stdout':'','stderr':'','exit_code':None}
        if result.get('status')!='completed':
            return {**result,'cleanup':cleanup,'artifacts':{}}
        try:artifacts=collect_outputs(output)
        except (ValueError,OSError):
            return {'status':'failed','reason':'Invalid or oversized output',
                    'cleanup':cleanup,'artifacts':{},'stdout':'','stderr':'','exit_code':None}
        return {**result,'cleanup':cleanup,'artifacts':artifacts,
                'isolation':'worker-reported-disposable-container-not-hypervisor-attested'}
