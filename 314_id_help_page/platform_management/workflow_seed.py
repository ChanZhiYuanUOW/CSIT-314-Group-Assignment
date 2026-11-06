"""Optional large deterministic workflow fixtures; never changes shared accounts."""
from datetime import datetime,timedelta,timezone
import click
from entities import RegisteredUser
from .db import get_db,init_db
from .workflow_entities import WorkflowEntity as E
from .entities import PlatformData,utc_now


def seed_workflows():
    db=get_db()
    if db.execute("SELECT 1 FROM demo_metadata WHERE name='workflow_demo_v1'").fetchone():
        click.echo('Workflow fixtures already exist; unchanged.');return
    users=RegisteredUser._readAll()
    managers=[u for u in users if u['role']=='Platform Management' and u['status']=='Active']
    owners=[u for u in users if u['role']=='Interior Designer' and u['status']=='Active']
    customers=[u for u in users if u['role']=='Customer' and u['status']=='Active']
    category=db.execute('SELECT id FROM categories ORDER BY id LIMIT 1').fetchone()
    if not managers or not owners or not customers or not category: raise click.ClickException('Run seed-pm-demo first; active shared manager/designer/customer accounts are required.')
    manager=next((u for u in managers if u['username']=='pm_demo'),managers[0])['user_id']
    now=datetime.now(timezone.utc)
    stamp=lambda t:t.isoformat(timespec='seconds')
    with db:
        for i in range(100):
            owner=owners[i%len(owners)]['user_id'];when=stamp(now-timedelta(days=110-i))
            # First three appeals pending; remaining approved, with corresponding visibility.
            pending=i<3
            pid=db.execute('INSERT INTO projects(title,description,designer_id,category_id,status,featured,created_at,restriction_version) VALUES(?,?,?,?,?,0,?,?)',(f'[WORKFLOW DEMO] Residence {i+1:03}','Synthetic moderation-and-appeal example.',owner,category['id'],'hidden' if pending else 'published',when,1 if pending else 2)).lastrowid
            cid=db.execute("INSERT INTO moderation_cases(project_id,state,priority,assigned_to,decision,reason,previous_status,restriction_version,created_at,resolved_at) VALUES(?,'resolved','normal',?,'hide',?,'published',1,?,?)",(pid,manager,'Demo decision: ownership of photos needed clarification.',when,when)).lastrowid
            rid=db.execute("INSERT INTO content_reports(project_id,reporter_id,reason,evidence,status,created_at,reviewed_by,reviewed_at,decision_note) VALUES(?,?,?,?,'actioned',?,?,?,?)",(pid,customers[i%len(customers)]['user_id'],'Demo photo ownership complaint','Synthetic customer evidence.',when,manager,when,'Resolved as demo restriction.')).lastrowid
            db.execute('INSERT INTO case_reports(report_id,case_id) VALUES(?,?)',(rid,cid))
            aid=db.execute('INSERT INTO project_appeals(case_id,owner_id,explanation,evidence,state,reviewer_id,reason,created_at,decided_at) VALUES(?,?,?,?,?,?,?,?,?)',(cid,owner,'I own these project photos.','Demo ownership evidence and original photo reference.','pending' if pending else 'approved',None if pending else manager,'' if pending else 'Demo evidence accepted.',when,None if pending else when)).lastrowid
            E.notify(db,owner,f'Demo appeal #{aid}: '+('awaiting review' if pending else 'approved'))
            E.audit(db,manager,'workflow_demo',f'Case #{cid} / Appeal #{aid}','Synthetic workflow history.')
            # Non-overlapping historical bookings, one per day. Three hidden fixtures are suppressed anyway.
            begin=now-timedelta(days=150-i)
            db.execute('INSERT INTO feature_schedules(project_id,slot,starts_at,ends_at,created_by,reason,created_at) VALUES(?,1,?,?,?,?,?)',(pid,stamp(begin),stamp(begin+timedelta(hours=2)),manager,'Synthetic expired booking.',when))
        db.execute("INSERT INTO demo_metadata(name) VALUES('workflow_demo_v1')")
    click.echo('Added 100 cases, 100 appeals, 100 schedules, 100 reports, 100 demo projects, 100 notifications and 100 audit entries. First three appeals await review.')


def init_app(app):
    @app.cli.command('seed-workflow-demo')
    def seed(): init_db();seed_workflows()

    @app.cli.command('set-designer-demo-password')
    def designer_password():
        """Set password for the owner of the first original demo project, for live walkthroughs."""
        p=get_db().execute("SELECT designer_id FROM projects WHERE title LIKE '[DEMO]%' ORDER BY id LIMIT 1").fetchone()
        if not p: raise click.ClickException('Run seed-pm-demo first.')
        rows=RegisteredUser._readAll();user=next((u for u in rows if u['user_id']==str(p['designer_id'])),None)
        if not user or user['role']!='Interior Designer' or user['status']!='Active': raise click.ClickException('First project owner is not an active designer. Use an active owner account.')
        click.echo(f'Demo owner username: {user["username"]}')
        password=click.prompt('New designer demo password',hide_input=True,confirmation_prompt=True)
        if len(password)<8: raise click.ClickException('At least 8 characters required.')
        user['password']=RegisteredUser.hashPassword(password);RegisteredUser._writeAll(rows)
        click.echo('Password updated for this existing designer in your local copy.')
