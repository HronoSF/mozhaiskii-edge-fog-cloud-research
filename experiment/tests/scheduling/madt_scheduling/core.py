"""Pure task, causal-ledger and placement contracts. Durations are integer ns."""
from dataclasses import dataclass, replace
import hashlib

WORKERS = ('E', 'F', 'C')
CLASSES = tuple((w, b) for w in (200_000, 800_000) for b in (65_536, 1_048_576))
POLICIES = ('rr', 'compute_ect', 'network_ect')
PHASES = ('sender_wait', 'uploading', 'worker_wait', 'executing', 'returning', 'completed')
MAX_TASKS = 8192

@dataclass(frozen=True)
class Task:
    id: int
    iterations: int
    size: int
    release_ns: int = 0
    seed: int = 0

    def __post_init__(self):
        if type(self.id) is not int or not 0 <= self.id < 2**64:
            raise ValueError('ID must be uint64')
        if (self.iterations, self.size) not in CLASSES:
            raise ValueError('Unknown work/input class')
        if type(self.release_ns) is not int or self.release_ns < 0:
            raise ValueError('Invalid release')
        if type(self.seed) is not int:
            raise ValueError('Invalid seed')

    @property
    def reservation(self):
        return self.size + 1_048_576

    @property
    def key(self):
        return f'{self.iterations}:{self.size}'


def payload(task):
    block = hashlib.sha256(f'ehu-input-v1|{task.seed}|{task.id}'.encode()).digest()
    return (block * ((task.size + 31) // 32))[:task.size]


def compute(task, data):
    if len(data) != task.size:
        raise ValueError('Incomplete input')
    digest = hashlib.sha256(data).digest()
    value = hashlib.pbkdf2_hmac('sha256', digest, b'ehu-baseline-v1', task.iterations, 32)
    return value + task.id.to_bytes(8, 'big') + bytes(216)


def trace(n=12, horizon_ns=6_000_000_000, seed=0, scenario='steady'):
    if type(n) is not int or n % 4 or not 4 <= n <= 4096:
        raise ValueError('N must be a multiple of four in [4,4096]')
    if type(horizon_ns) is not int or horizon_ns <= 0:
        raise ValueError('Invalid horizon')
    if scenario == 'steady':
        times = [horizon_ns*i//n for i in range(n)]
    elif scenario == 'burst':
        events = [(2*horizon_ns*i//n, 0, i) for i in range(n//2)]
        events += [(horizon_ns//3 + horizon_ns*k//(3*n), 1, k) for k in range(n//4)]
        events += [(2*horizon_ns//3 + horizon_ns*k//(3*n), 2, k) for k in range(n//4)]
        times = [t for t, _, _ in sorted(events)]
    else:
        raise ValueError('Unknown scenario')
    order = sorted(range(n), key=lambda i: (hashlib.sha256(f'ehu-workload-v1|{seed}|{i}'.encode()).digest(), i))
    return tuple(Task(i, *CLASSES[index % 4], release_ns=t, seed=seed)
                 for i, (t, index) in enumerate(zip(times, order)))


@dataclass(frozen=True)
class Profiles:
    # Tuple storage makes the complete policy input immutable, not merely its top level.
    service: tuple   # (worker, class_key, ns)
    transport: tuple # (worker, size, input_ns, ack_ns, result_ns)

    @classmethod
    def from_dict(cls, value):
        service, transport = [], []
        for worker in WORKERS:
            for w, size in CLASSES:
                ns = value['service'][worker][f'{w}:{size}']
                if type(ns) is not int or ns <= 0:
                    raise ValueError('Service estimate must be a positive integer')
                service.append((worker, f'{w}:{size}', ns))
            for size in (65_536, 1_048_576):
                costs = value['transport'][worker][str(size)]
                if len(costs) != 3 or any(type(v) is not int or v < 0 for v in costs):
                    raise ValueError('Invalid transport estimate')
                transport.append((worker, size, *costs))
        return cls(tuple(service), tuple(transport))

    def s(self, worker, task):
        return next(ns for j, key, ns in self.service if (j, key) == (worker, task.key))

    def uv(self, worker, size):
        return next((u, a, v) for j, b, u, a, v in self.transport if (j, b) == (worker, size))


@dataclass(frozen=True)
class Pending:
    task: Task
    seq: int
    phase: str = 'sender_wait'
    e: int | None = None
    x: int | None = None


@dataclass(frozen=True)
class View:
    worker: str
    online: bool
    pending: tuple
    active_upload: int | None
    credits: int
    reserved: int
    last_send: int | None
    last_receipt: int | None


@dataclass(frozen=True)
class Snapshot:
    task: Task
    views: tuple
    profiles: Profiles
    order: tuple = WORKERS


def eligible(view, task, k=32, memory=64*1_048_576):
    return view.online and view.credits < k and view.reserved + task.reservation <= memory


def predict(view, candidate, profiles, now, network=True):
    """Model §5: separate active upload receiver readiness and ACK-slot release."""
    pending = view.pending
    running = [p for p in pending if p.phase == 'executing']
    if len(running) > 1:
        raise ValueError('More than one reported running job')
    execution = now
    if running:
        p = running[0]
        if p.x is None or p.x > now:
            raise ValueError('Invalid causal running timestamp')
        execution += max(0, profiles.s(view.worker, p.task) - (now-p.x))
    upload = now
    active = next((p for p in pending if p.task.id == view.active_upload), None)
    if view.active_upload is not None and (active is None or active.e is None):
        # Completed-before-ACK jobs remain in the ledger until ACK but retain e.
        raise ValueError('Active upload lacks controller start')
    if active and network:
        u, ack, _ = profiles.uv(view.worker, active.task.size)
        upload = max(now, active.e + u + ack)
    for p in (*pending, Pending(candidate, 0)):
        if p.phase in ('executing', 'returning', 'completed'):
            continue
        u, ack, _ = profiles.uv(view.worker, p.task.size) if network else (0, 0, 0)
        if p.phase == 'worker_wait':
            ready = now
        elif active is not None and p.task.id == active.task.id:
            ready = max(now, p.e + u) if network else now
        else:
            ready = upload + u
            upload = ready + ack
        execution = max(execution, ready) + profiles.s(view.worker, p.task)
    result = profiles.uv(view.worker, candidate.size)[2] if network else 0
    return execution + result


def choose(policy, snapshot, now, cursor=0, k=32, memory=64*1_048_576):
    if policy not in POLICIES:
        raise ValueError('Unknown policy')
    candidates = {v.worker:v for v in snapshot.views if eligible(v, snapshot.task, k, memory)}
    if not candidates:
        return None, cursor, ()
    if policy == 'rr':
        for delta in range(len(snapshot.order)):
            index = (cursor+delta) % len(snapshot.order)
            worker = snapshot.order[index]
            if worker in candidates:
                return worker, (index+1) % len(snapshot.order), ()
    costs = tuple((j, predict(candidates[j], snapshot.task, snapshot.profiles, now,
                              network=policy=='network_ect')) for j in snapshot.order if j in candidates)
    worker = min(costs, key=lambda item:item[1])[0]  # stable published tie order
    return worker, cursor, costs


class Ledger:
    """Controller-known phases only. Actual credit release needs validated result."""
    def __init__(self, k=32, memory=64*1_048_576):
        if not 1 <= k <= 32 or memory <= 0:
            raise ValueError('Invalid finite limits')
        self.k, self.memory = k, memory
        self.jobs = {}
        self.workers = {j:dict(epoch=None, report_seq=-1, online=False, send=None,
                               receipt=None, active=None, seq=0) for j in WORKERS}

    def admit(self, task):
        if task.id in self.jobs or len(self.jobs) >= MAX_TASKS:
            raise ValueError('Repeated ID or run task bound exceeded')
        self.jobs[task.id] = dict(task=task, state='global_wait', worker=None, seq=None,
                                  phase='sender_wait', e=None, f=None, x=None, y=None, released=False)

    def views(self):
        result=[]
        for j, state in self.workers.items():
            entries=[r for r in self.jobs.values() if r['worker']==j]
            pending=tuple(Pending(r['task'],r['seq'],r['phase'],r['e'],r['x'])
                          for r in sorted(entries,key=lambda r:r['seq'])
                          if not r['released'] or state['active']==r['task'].id)
            unresolved=[r for r in entries if not r['released']]
            result.append(View(j,state['online'],pending,state['active'],len(unresolved),
                               sum(r['task'].reservation for r in unresolved),state['send'],state['receipt']))
        return tuple(result)

    def begin(self, task_id):
        row=self.jobs[task_id]
        if row['state']!='global_wait':raise ValueError('Duplicate decision')
        row['state']='decision'

    def commit(self, task_id, worker):
        r=self.jobs[task_id]
        v=next(v for v in self.views() if v.worker==worker)
        if r['state'] not in ('global_wait','decision') or not eligible(v,r['task'],self.k,self.memory):
            raise ValueError('Ineligible/duplicate commitment')
        self.workers[worker]['seq']+=1
        r.update(worker=worker,seq=self.workers[worker]['seq'],state='sender_wait')
        return r['seq']

    def uploading(self, task_id, now):
        r=self.jobs[task_id];s=self.workers[r['worker']]
        if r['state']!='sender_wait' or s['active'] is not None:
            raise ValueError('Upload slot/order violation')
        r.update(state='uploading',phase='uploading',e=now);s['active']=task_id

    def milestone(self, worker, task_id, phase, x=None):
        r=self.jobs.get(task_id)
        if r is None or r['worker']!=worker or phase not in PHASES:
            raise ValueError('Unknown ID/worker/phase')
        if PHASES.index(phase) > PHASES.index(r['phase']):
            r['phase']=phase
        if x is not None:
            if r['x'] is not None and r['x']!=x:
                raise ValueError('Changed start timestamp')
            r['x']=x
        if not r['released'] and r['state']!='failed':
            r['state']=r['phase']

    def observe(self, worker, task_id, phase, *, f, x=None, y=None, receipt):
        """Reconcile positive peer evidence with the controller's actual upload."""
        row=self.jobs.get(task_id)
        if row is None or row['worker']!=worker or row['e'] is None:
            raise ValueError('Worker milestone for unknown or unsent input')
        values=dict(f=f)
        if phase in ('executing','returning'):values['x']=x
        if phase=='returning':values['y']=y
        stamps=[row['e'],*values.values(),receipt]
        if phase not in ('worker_wait','executing','returning') or any(type(t) is not int or t<0 for t in stamps) or stamps!=sorted(stamps):
            raise ValueError('Worker milestone predates upload or exceeds receipt')
        for key,value in values.items():
            if row[key] is not None and row[key]!=value:
                raise ValueError('Changed '+key+' timestamp')
        row.update(values)
        self.milestone(worker,task_id,phase,x)

    def ack(self, worker, task_id, f, receipt):
        s=self.workers[worker]
        if s['active']!=task_id:
            raise ValueError('ACK does not match active upload')
        self.observe(worker,task_id,'worker_wait',f=f,receipt=receipt);s['active']=None

    def telemetry(self, worker, epoch, sequence, send, receipt, online, items):
        s=self.workers[worker]
        if s['epoch'] is not None and epoch!=s['epoch']:
            raise ValueError('Unexpected worker restart')
        if sequence<=s['report_seq']:
            return False
        if send>receipt:
            raise ValueError('Worker timestamp after receipt')
        if type(sequence) is not int or sequence<0 or type(send) is not int or type(receipt) is not int or type(online) is not bool:
            raise ValueError('Invalid telemetry types')
        seen=set()
        for item in items:
            if item['id'] in seen or item['phase'] not in ('worker_wait','executing','returning'):
                raise ValueError('Duplicate/invalid telemetry item')
            seen.add(item['id'])
            keys=('f',) if item['phase']=='worker_wait' else ('f','x') if item['phase']=='executing' else ('f','x','y')
            times=[item[k] for k in keys]
            if any(type(v) is not int or v<0 for v in times) or times!=sorted(times) or times[-1]>send:
                raise ValueError('Impossible telemetry milestones')
        # Merge all phases before checking the one-running invariant.
        for item in items:
            self.observe(worker,item['id'],item['phase'],f=item['f'],x=item.get('x'),y=item.get('y'),receipt=send)
        s.update(epoch=epoch,report_seq=sequence,send=send,receipt=receipt,online=online)
        if sum(p.phase=='executing' for p in next(v for v in self.views() if v.worker==worker).pending)>1:
            raise ValueError('Contradictory running report')
        return True

    def complete(self, worker, task_id, valid, *, f=None, x=None, y=None, receipt=None):
        r=self.jobs.get(task_id)
        if r is None or r['worker']!=worker:
            raise ValueError('Unknown result ID/worker')
        if r['released'] or r['state']=='failed':
            return False
        if not valid:
            r['state']='failed'  # unresolved credit remains until explicit shutdown
            return False
        self.observe(worker,task_id,'returning',f=f,x=x,y=y,receipt=receipt)
        self.milestone(worker,task_id,'completed');r.update(state='completed',released=True)
        return True


def timing_components(times):
    order=('a','g','b','c','d','e','f','x','y','z')
    stamps=[times[key] for key in order]
    if any(type(v) is not int for v in stamps) or stamps!=sorted(stamps):
        raise ValueError('Impossible timestamp order')
    parts=tuple(b-a for a,b in zip(stamps,stamps[1:]))
    if sum(parts)!=times['z']-times['a']:
        raise ValueError('Latency accounting error')
    return parts
