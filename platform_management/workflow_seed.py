"""Optional large deterministic workflow fixtures; never changes shared accounts."""
from datetime import datetime,timedelta,timezone
import click
from entities import RegisteredUser
from .db import get_db,init_db
from .workflow_entities import WorkflowEntity as E
from .entities import PlatformData,utc_now


def seed_workflows():
    db=get_db()
    if db.first('demo_metadata', name='workflow_demo_v1'):
        click.echo('Workflow fixtures already exist; unchanged.');return
    users=RegisteredUser._readAll()
    managers=[u for u in users if u['role']=='Platform Management' and u['status']=='Active']
    owners=[u for u in users if u['role']=='Interior Designer' and u['status']=='Active']
    customers=[u for u in users if u['role']=='Customer' and u['status']=='Active']
    category = min(db.all('categories'),key=lambda c:c['id'],default=None)
    if not managers or not owners or not customers or not category: raise click.ClickException('Run seed-pm-demo first; active shared manager/designer/customer accounts are required.')
    manager=next((u for u in managers if u['username']=='pm_demo'),managers[0])['user_id']
    now=datetime.now(timezone.utc)
    stamp=lambda t:t.isoformat(timespec='seconds')
    with db:
        for i in range(100):
            owner=owners[i%len(owners)]['user_id'];when=stamp(now-timedelta(days=110-i))
            # First three appeals pending; remaining approved, with corresponding visibility.
            pending=i<3
            pid=db.add('projects', title=f'[WORKFLOW DEMO] Residence {i + 1:03}', description='Synthetic moderation-and-appeal example.', designer_id=owner, category_id=category['id'], status='hidden' if pending else 'published', featured=0, created_at=when, restriction_version=1 if pending else 2)['id']
            cid=db.add('moderation_cases', project_id=pid, violation_category='Copyright infringement', state='resolved', priority='normal', assigned_to=manager, decision='hide', reason='Demo decision: ownership of photos needed clarification.', previous_status='published', restriction_version=1, created_at=when, resolved_at=when)['id']
            rid=db.add('content_reports', project_id=pid, reporter_id=customers[i % len(customers)]['user_id'], reason='Demo photo ownership complaint', evidence='Synthetic customer evidence.', status='actioned', created_at=when, reviewed_by=manager, reviewed_at=when, decision_note='Resolved as demo restriction.')['id']
            db.add('case_reports', report_id=rid, case_id=cid)
            aid=db.add('project_appeals', case_id=cid, owner_id=owner, explanation='I own these project photos.', evidence='Demo ownership evidence and original photo reference.', state='pending' if pending else 'approved', reviewer_id=None if pending else manager, reason='' if pending else 'Demo evidence accepted.', created_at=when, decided_at=None if pending else when)['id']
            E.notify(db,owner,f'Demo appeal #{aid}: '+('awaiting review' if pending else 'approved'))
            E.audit(db,manager,'workflow_demo',f'Case #{cid} / Appeal #{aid}','Synthetic workflow history.')
            # Non-overlapping historical bookings, one per day. Three hidden fixtures are suppressed anyway.
            begin=now-timedelta(days=150-i)
            db.add('feature_schedules', project_id=pid, slot=1, starts_at=stamp(begin), ends_at=stamp(begin + timedelta(hours=2)), created_by=manager, reason='Synthetic expired booking.', created_at=when)
        db.add('demo_metadata', name='workflow_demo_v1')
    click.echo('Added 100 cases, 100 appeals, 100 schedules, 100 reports, 100 demo projects, 100 notifications and 100 audit entries. First three appeals await review.')


def init_app(app):
    @app.cli.command('seed-workflow-demo')
    def seed(): init_db();seed_workflows()

    @app.cli.command('set-designer-demo-password')
    def designer_password():
        """Set password for the owner of the first original demo project, for live walkthroughs."""
        p = next((r for r in get_db().all('projects') if r['title'].startswith('[DEMO]')),None)
        if not p: raise click.ClickException('Run seed-pm-demo first.')
        rows=RegisteredUser._readAll();user=next((u for u in rows if u['user_id']==str(p['designer_id'])),None)
        if not user or user['role']!='Interior Designer' or user['status']!='Active': raise click.ClickException('First project owner is not an active designer. Use an active owner account.')
        click.echo(f'Demo owner username: {user["username"]}')
        password=click.prompt('New designer demo password',hide_input=True,confirmation_prompt=True)
        if len(password)<8: raise click.ClickException('At least 8 characters required.')
        user['password']=RegisteredUser.hashPassword(password);RegisteredUser._writeAll(rows)
        click.echo('Password updated for this existing designer in your local copy.')
