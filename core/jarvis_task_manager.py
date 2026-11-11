"""Supervised, crash-aware sequential workspace tasks.

No model-generated shell commands; only new files/folders and an approved run.
Tools do NOT execute until the existing JARVIS approval dispatcher approves them.
"""
import fcntl
import hashlib
import json
import re
import secrets
from contextlib import contextmanager
from pathlib import Path

from core.jarvis_task_state import TaskStore
from core.jarvis_task_planner import make_plan, PlanningError

MAX_FILES=4
MAX_TOTAL_SOURCE=16000
MAX_STEPS=12
SLUG=re.compile(r'^[a-z][a-z0-9_-]{2,32}$')

class TaskError(ValueError): pass


def _relative(value):
    if not isinstance(value,str) or not value or '\\' in value or '\x00' in value:
        raise TaskError('Invalid workspace-relative file path.')
    p=Path(value)
    if p.is_absolute() or '..' in p.parts or '.' in p.parts or len(p.parts)>4 or any(x.startswith('.') for x in p.parts):
        raise TaskError('Paths must be ordinary relative paths within the new project.')
    return p


def validated_plan(root: Path, plan: dict):
    if not isinstance(plan,dict) or plan.get('language') not in ('verilog','python'):
        raise TaskError('Task planner returned unsupported language.')
    slug=plan.get('project')
    if not isinstance(slug,str) or not SLUG.fullmatch(slug):
        raise TaskError('Task planner returned an invalid project name.')
    base=Path('projects')/slug
    project=root/base
    if project.exists() or project.is_symlink():
        raise TaskError(f'Project {base} already exists. No existing projects will be overwritten.')
    files=plan.get('files')
    if not isinstance(files,list) or not 1<=len(files)<=MAX_FILES:
        raise TaskError('Plan must contain 1–4 new source files.')
    names=set()
    steps=[]
    paths=[]
    total=0
    for file in files:
        if not isinstance(file,dict) or not isinstance(file.get('content'),str):
            raise TaskError('Invalid planned source file.')
        path=_relative(file.get('path'))
        suffix=path.suffix.lower()
        if suffix not in (('.v','.sv') if plan['language']=='verilog' else ('.py',)):
            raise TaskError('Plan contains unsupported file type.')
        if str(path) in names or not path.name:
            raise TaskError('Duplicate or invalid file path.')
        names.add(str(path)); paths.append(path)
        content=file['content']
        total+=len(content.encode('utf-8'))
        if not content.strip() or len(content)>10000:
            raise TaskError('Source file is empty or too large.')
    if total>MAX_TOTAL_SOURCE:
        raise TaskError('Plan is too large; ask for a smaller project.')
    run=plan.get('run')
    if not isinstance(run,dict):
        raise TaskError('Plan must include a run configuration.')
    filename=_relative(run.get('filename'))
    tb=run.get('testbench') or ''
    tb_path=_relative(tb) if tb else None
    if filename not in paths or (tb_path and tb_path not in paths):
        raise TaskError('Simulation must reference newly planned project files.')
    if plan['language']=='verilog' and (not tb_path or tb_path==filename):
        raise TaskError('Verilog autonomous tasks require a separate testbench.')
    if plan['language']=='python' and tb_path:
        raise TaskError('Python tasks cannot have a Verilog testbench.')
    dirs={Path('projects'),base}
    for path in paths:
        parent=(base/path).parent
        while parent!=Path('projects'):
            dirs.add(parent)
            parent=parent.parent
    # Parent before children. All paths inside a brand-new projects/<slug> subtree.
    for folder in sorted(dirs,key=lambda p:(len(p.parts),str(p))):
        steps.append({'kind':'mkdir','path':str(folder)})
    for item in files:
        steps.append({'kind':'create','path':str(base/_relative(item['path'])),'content':item['content']})
    steps.append({'kind':'run','filename':str(base/filename),
                  'testbench':str(base/tb_path) if tb_path else ''})
    if len(steps)>MAX_STEPS:
        raise TaskError('Plan has too many steps.')
    # Preflight every path including symlink ancestors.
    for item in steps:
        rel=item.get('path') or item.get('filename')
        target=(root/rel).resolve()
        if not target.is_relative_to(root.resolve()) or (rel != 'projects' and not target.is_relative_to(project.resolve())):
            raise TaskError('Planned step escapes the workspace project.')
    return steps


class TaskManager:
    def __init__(self, root, *, store_path=None, approval_lookup, queue_approval, log_action=None, model=None, ollama_url=None):
        self.root=Path(root).resolve()
        self.store=TaskStore(store_path or self.root.parent/'jarvis_tasks.db')
        self.lock_path=self.root/'.jarvis_tasks.lock'
        self.approval_lookup=approval_lookup  # (task_id, step_index) => id,status,result or None
        self.queue_approval=queue_approval  # (kind,payload,description) => ID
        self.log_action=log_action
        self.model=model
        self.ollama_url=ollama_url

    @contextmanager
    def lock(self):
        with self.lock_path.open('a+b') as fp:
            fcntl.flock(fp.fileno(),fcntl.LOCK_EX)
            try: yield
            finally: fcntl.flock(fp.fileno(),fcntl.LOCK_UN)

    def start(self, objective, model, ollama_url):
        # Generate a plan without holding a filesystem lock during Ollama latency.
        if self.store.active():
            return 'Another autonomous task is active. Use /task status or /task cancel.'
        try:
            plan=make_plan(objective,model,ollama_url)
        except (PlanningError,TaskError,ValueError) as exc:
            return f'Task planning stopped: {exc} No new files were created.'
        with self.lock():
            if self.store.active():
                return 'Another autonomous task is active. Use /task status or /task cancel.'
            try:
                steps=validated_plan(self.root,plan)
                task_id=secrets.token_hex(6)
                self.store.create(task_id,objective,plan,steps)
                return self._advance(task_id)
            except (PlanningError,TaskError,ValueError) as exc:
                return f'Task planning stopped: {exc} No new files were created.'

    def start_repair_test(self, variant='semicolon'):
        """Create a disposable project with an intentional compiler error.

        This only creates NEW files. Repairs and simulations use the normal
        approval workflow; existing projects are not modified.
        """
        if variant not in ('semicolon', 'port', 'signal'):
            return 'Unknown repair test variant.'
        from core.jarvis_task_planner import _counter_plan
        if self.store.active():
            return 'Another autonomous task is active. Use /task status or /task cancel.'
        objective = 'Create a 4-bit Verilog up-counter and verify its self-checking testbench.'
        plan = _counter_plan(objective)
        if plan is None:
            return 'Repair test unavailable: trusted counter fixture is missing.'
        plan['project'] = ('repair_demo_' if variant == 'semicolon' else 'repair_' + variant + '_') + secrets.token_hex(4)
        tb_name = plan['run']['testbench']
        rtl_name = plan['run']['filename']
        tb = [item for item in plan['files'] if item['path'] == tb_name]
        rtl = [item for item in plan['files'] if item['path'] == rtl_name]
        if len(tb) != 1 or len(rtl) != 1:
            return 'Repair test unavailable: unexpected counter fixture.'
        if variant == 'semicolon':
            source = tb[0]['content']
            if source.count('        $finish;') != 1:
                return 'Repair test unavailable: cannot locate $finish fixture.'
            tb[0]['content'] = source.replace('        $finish;', '        $finish', 1)
        elif variant == 'port':
            source = tb[0]['content']
            if source.count('.clk(clk)') != 1:
                return 'Repair test unavailable: cannot locate port fixture.'
            tb[0]['content'] = source.replace('.clk(clk)', '.clock_invalid(clk)', 1)
        else:
            source = rtl[0]['content']
            if source.count("count <= count + 4'd1;") != 1:
                return 'Repair test unavailable: cannot locate signal fixture.'
            rtl[0]['content'] = ('`default_nettype none\n' +
                source.replace("count <= count + 4'd1;", "count <= missing_signal + 4'd1;", 1) +
                '`default_nettype wire\n')
        plan['_repair_test'] = True
        plan['_repair_test_kind'] = variant
        with self.lock():
            if self.store.active():
                return 'Another autonomous task is active. Use /task status or /task cancel.'
            try:
                steps = validated_plan(self.root, plan)
                task_id = secrets.token_hex(6)
                self.store.create(task_id, objective, plan, steps)
                outcome = self._advance(task_id)
                return ('Repair test created a NEW disposable project with a deliberately '
                        'broken Verilog source (' + variant + ').\n' + outcome +
                        '\nApprove the initial simulation to trigger compiler diagnostics.')
            except (PlanningError, TaskError, ValueError) as exc:
                return f'Repair test stopped: {exc} No existing projects were modified.'

    def status(self):
        with self.lock():
            task=self.store.active()
            if task is None: return 'No active autonomous task.'
            step=f"{task['step_index']}/{len(task['steps'])}"
            out=f"Task `{task['id']}`: {task['status']} ({step} steps complete)."
            if task['approval_id']: out+=f" Pending approval `{task['approval_id']}`."
            if task['note']: out+=f" {task['note'][:300]}"
            return out

    def cancel(self):
        with self.lock():
            task=self.store.active()
            if not task: return 'No active autonomous task.', ''
            self.store.update(task['id'],status='cancelled',note='Cancelled by user. Existing created files remain.')
            return f"Task `{task['id']}` cancelled. Existing files were not deleted.", task['approval_id']

    def _safe_target(self, rel):
        path=(self.root/rel).resolve()
        if not path.is_relative_to(self.root/'projects'):
            raise TaskError('Task tried to access outside workspace/projects.')
        return path

    def _advance(self, task_id):
        # Must be called with lock held. This function never runs an approved program.
        while True:
            task=self.store.get(task_id)
            if task is None: return 'Unknown task.'
            if task['status'] in ('completed','failed','cancelled'):
                return f"Task `{task_id}` is {task['status']}. {task['note']}"
            idx=task['step_index']; steps=task['steps']
            if idx>=len(steps):
                self.store.update(task_id,status='completed',approval_id='',note='All approved steps completed; review simulation output for functional correctness.')
                return f"Task `{task_id}` completed its workflow. Review test results to confirm correctness."
            step=steps[idx]
            try:
                if step['kind']=='mkdir':
                    path=self._safe_target(step['path'])
                    path.mkdir(exist_ok=True) # idempotent recovery; preflight ensured new project
                    if not path.is_dir(): raise TaskError('Folder could not be verified.')
                    if self.log_action: self.log_action('create_folder',f"Task {task_id}: {step['path']}",f"Verified {step['path']}")
                elif step['kind']=='create':
                    path=self._safe_target(step['path']); data=step['content']
                    if path.exists():
                        # After a crash, accept only identical content, never overwrite.
                        if not path.is_file() or path.read_text(encoding='utf-8')!=data:
                            raise TaskError(f'Existing file differs: {step["path"]}. Nothing overwritten.')
                    else:
                        with path.open('x',encoding='utf-8') as handle: handle.write(data)
                    if path.read_text(encoding='utf-8')!=data:
                        raise TaskError('New file verification failed.')
                    if self.log_action: self.log_action('create_file',f"Task {task_id}: {step['path']}",f"Verified {step['path']}")
                elif step['kind']=='run':
                    existing=self.approval_lookup(task_id,idx)
                    # After an approved repair, old completed run actions must not be replayed.
                    if task['plan'].get('_repair_stage') == 'rerun':
                        existing = None
                    if existing:
                        action_id,status,result=existing
                        if status=='completed':
                            return self._apply_run_result(task_id,idx,result)
                        if status in ('denied','failed','executing'):
                            self.store.update(task_id,status='interrupted',approval_id=action_id,
                                              note=f'Approval is {status}; no automatic retry.')
                            return f"Task `{task_id}` interrupted: action `{action_id}` is {status}. No retry performed."
                        self.store.update(task_id,status='waiting_approval',approval_id=action_id)
                        return f"Task `{task_id}` waiting for approval `{action_id}`."
                    from tools.jarvis_workspace_runner import validate_request
                    payload=validate_request(self.root,step['filename'],step['testbench'],'')
                    payload['_task_id']=task_id;payload['_task_step']=idx
                    review=[]
                    for rel in (step['filename'],step['testbench']):
                        if rel:
                            path=self._safe_target(rel)
                            review.append(f'=== {rel} ===\n'+path.read_text(encoding='utf-8')[:9000])
                    payload['_review']='\n\n'.join(review)[:16000]
                    action_id=self.queue_approval('run_workspace_program',payload,
                              f"Task {task_id}: simulate or run {step['filename']}")
                    if task['plan'].get('_repair_stage') == 'rerun':
                        plan = task['plan']; plan['_repair_stage'] = 'running'
                        self.store.update(task_id, plan=plan)
                    self.store.update(task_id,status='waiting_approval',approval_id=action_id,
                                      note='Source files created and verified. Execution requires approval.')
                    return f"Task `{task_id}` created its files. Action waiting for approval `{action_id}`."
                else: raise TaskError('Unknown planned step.')
                self.store.update(task_id,step_index=idx+1,status='active',note=f"Completed {step['kind']}: {step['path']}")
            except Exception as exc:
                self.store.update(task_id,status='failed',note=f"Step {idx+1} failed: {type(exc).__name__}: {exc}"[:450])
                return f"Task `{task_id}` stopped at step {idx+1}: {type(exc).__name__}: {exc}"

    def _apply_run_result(self,task_id,idx,result):
        # JARVIS_TASK_REPORTING_V1: deterministic report, no additional LLM calls.
        result = str(result or '')
        task = self.store.get(task_id)
        if not task:
            return 'Task not found; review action history.'
        match = re.search(r'(?:Simulation exit code|Exit code):\s*(-?\d+)', result)
        if result.startswith('Verilog compile FAILED'):
            return self._propose_repair(task_id, idx, task, result)
        if match is None or int(match.group(1)) != 0:
            self.store.update(task_id,status='failed',approval_id='',note='Execution failed; full diagnostics in the action history.')
            return f'Task `{task_id}` failed during execution. Review the action history.'
        if re.search(r'(?im)^\s*(?:FAIL(?:ED)?\b|ERROR\s*:)', result):
            self.store.update(task_id,status='failed',approval_id='',note='Self-checking testbench reported failure.')
            return f'Task `{task_id}` failed verification. Review the action history.'
        is_verilog = task['plan'].get('language') == 'verilog'
        passed = is_verilog and bool(re.search(r'(?im)^\s*PASS\s*:', result))
        waveform = re.search(r'(?m)^Waveform\(s\):\s*(.+)$', result)
        note = ('Testbench reported PASS.' if passed else 'Execution succeeded; correctness not independently verified.')
        if waveform:
            note += ' Waveform: ' + waveform.group(1)[:180]
        self.store.update(task_id,step_index=idx+1,status='active',approval_id='',note=note)
        self._advance(task_id)
        self.store.update(task_id,note=note)
        message = f'Task `{task_id}` completed. ' + ('Verification: PASS.' if passed else 'Execution passed; verification unconfirmed.')
        if waveform:
            message += ' Waveform: ' + waveform.group(1)[:180]
        return message
    def _propose_repair(self, task_id, idx, task, diagnostics):
        """Compile failures only: propose a single-file repair for explicit approval."""
        plan = task['plan']
        attempts = int(plan.get('_repair_attempts', 0))
        if attempts >= 2 or not self.model or not self.ollama_url:
            self.store.update(task_id, status='failed', approval_id='',
                              note='Compilation still failed; automatic repair limit reached or model unavailable.')
            return f'Task `{task_id}` failed compilation. Repair limit reached; diagnostics saved in action history.'
        try:
            from core.jarvis_task_repair import propose_verilog_repair
            run = next(step for step in task['steps'] if step['kind'] == 'run')
            sources = {}
            for rel in (run['filename'], run['testbench']):
                path = self._safe_target(rel)
                sources[rel] = path.read_text(encoding='utf-8')
            filename, corrected = propose_verilog_repair(
                task['objective'], diagnostics, sources, self.model, self.ollama_url)
            if filename not in sources or corrected == sources[filename]:
                raise TaskError('Repair was unchanged or referenced an unknown file.')
            expected = hashlib.sha256(sources[filename].encode('utf-8')).hexdigest()
            payload = {'filename': filename, 'content': corrected,
                       '_expected_sha256': expected, '_task_repair': True,
                       '_task_id': task_id, '_task_step': idx,
                       '_review': 'Compiler-directed repair. Review changes before approving.'}
            action_id = self.queue_approval('write_file', payload,
                f'Task {task_id}: approve repair of {filename} (attempt {attempts + 1}/2)')
            plan['_repair_attempts'] = attempts + 1
            plan['_repair_stage'] = 'write'
            self.store.update(task_id, plan=plan, status='waiting_approval', approval_id=action_id,
                note='Compiler error diagnosed. Proposed source replacement awaits approval.')
            return (f'Task `{task_id}` could not compile. Proposed repair {attempts + 1}/2 '
                    f'awaits overwrite approval `{action_id}`; no file changed.')
        except Exception as exc:
            self.store.update(task_id, status='failed', approval_id='',
                note=f'Compile failed; repair proposal unavailable: {type(exc).__name__}: {exc}'[:450])
            return f'Task `{task_id}` failed compilation. Could not safely propose a repair: {exc}'

    def after_decision(self,action_id,approved,success,result):
        with self.lock():
            task=self.store.active()
            if not task or task['approval_id']!=action_id:
                # Recover crash between creation of action and task state update.
                if not task or task['steps'][task['step_index']]['kind']!='run': return ''
                found=self.approval_lookup(task['id'],task['step_index'])
                if not found or found[0]!=action_id:return ''
            is_repair = task['plan'].get('_repair_stage') == 'write'
            if not approved:
                self.store.update(task['id'],status='cancelled',note='Execution or repair approval denied; task stopped.',approval_id='')
                return f"Task `{task['id']}` stopped because approval was denied."
            if not success:
                self.store.update(task['id'],status='failed',note='Approved operation failed: '+str(result)[:250],approval_id='')
                return f"Task `{task['id']}` stopped: approved operation failed."
            if is_repair:
                plan = task['plan']; plan['_repair_stage'] = 'rerun'
                self.store.update(task['id'], plan=plan, status='active', approval_id='',
                                  note='Approved repair written; simulation requires separate approval.')
                return self._advance(task['id'])
            return self._apply_run_result(task['id'],task['step_index'],result)

    def may_execute(self,task_id,step_index,action_id):
        task=self.store.get(task_id)
        if not task or task['status'] in ('cancelled','failed','completed'):
            return False
        return (0 <= step_index < len(task['steps']) and
                task['step_index']==step_index and task['steps'][step_index]['kind']=='run') and (
            not task['approval_id'] or task['approval_id']==action_id)

    def resume(self):
        with self.lock():
            task=self.store.active()
            if not task:return 'No active autonomous task.'
            if task['status']=='interrupted':
                return f"Task `{task['id']}` is interrupted. Review the failed/unknown approval; no automatic re-execution."
            return self._advance(task['id'])
