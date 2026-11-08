"""Commands seed project fixtures only; shared accounts stay in Zhiyuan's CSV."""
import random
from datetime import datetime,timedelta,timezone
import click
from entities import RegisteredUser
from .db import get_db,init_db
from .entities import PlatformData


def seed_projects():
    db=get_db()
    if db.execute("SELECT 1 FROM demo_metadata WHERE name='pm_seed_v2'").fetchone():
        click.echo('Project demo data already exists; no changes made.');return
    accounts=RegisteredUser._readAll()
    managers=[u for u in accounts if u['role']=='Platform Management' and u['status']=='Active']
    designers=[u['user_id'] for u in accounts if u['role']=='Interior Designer']
    customers=[u['user_id'] for u in accounts if u['role']=='Customer']
    if not managers or not designers or not customers:
        raise click.ClickException('Shared CSV needs an active Platform Management account, a designer and a customer.')
    manager=next((u for u in managers if u['username']=='pm_demo'),managers[0])
    rng=random.Random(314);now=datetime.now(timezone.utc)
    def stamp(): return (now-timedelta(days=rng.randrange(90),hours=rng.randrange(24))).isoformat(timespec='seconds')
    styles=['Modern','Scandinavian','Industrial','Minimalist','Coastal','Rustic','Contemporary','Traditional','Eclectic','Japandi']
    spaces=['Apartment','Kitchen','Bedroom','Living Room','Office','Bathroom','Studio','Dining Room','Retail','House']
    with db:
        categories=[]
        for style in styles:
            for space in spaces:
                name=f'{style} {space}'
                db.execute('INSERT OR IGNORE INTO categories(name,description) VALUES(?,?)',(name,f'{style} ideas for a {space.lower()}.'))
                categories.append(db.execute('SELECT id FROM categories WHERE name=?',(name,)).fetchone()[0])
        projects=[]
        for i in range(100):
            status='published' if i<75 else ['draft','hidden','removed'][i%3]
            projects.append(db.execute('INSERT INTO projects(title,description,designer_id,category_id,status,featured,created_at) VALUES(?,?,?,?,?,?,?)',(f'[DEMO] {styles[i%10]} Residence {i+1:03}','Temporary project fixture for Platform Management integration.',designers[i%len(designers)],categories[i%80],status,int(i<8),stamp())).lastrowid)
        for kind,count in [('view',1000),('shortlist',300)]:
            db.executemany('INSERT INTO engagement_events(project_id,customer_id,kind,occurred_at) VALUES(?,?,?,?)',[(rng.choice(projects[:75]),rng.choice(customers),kind,stamp()) for _ in range(count)])
        for i in range(100):
            db.execute('INSERT INTO content_reports(project_id,reporter_id,reason,evidence,created_at) VALUES(?,?,?,?,?)',(projects[i%75],customers[i%len(customers)],['Misleading description','Possible copied content','Incorrect category'][i%3],f'DEMO evidence #{i+1}: review listing details.',stamp()))
            PlatformData.recordAudit(db,manager['user_id'],'demo_fixture',f'Demo fixture #{i+1}','Synthetic entry for pagination.')
        db.execute("INSERT INTO demo_metadata(name) VALUES('pm_seed_v2')")
    click.echo('Created 100 categories, 100 projects, 100 reports, 1300 engagement events and 100 audit entries. Shared account CSV files were not changed.')


def init_app(app):
    @app.cli.command('init-pm-db')
    def initialize():
        init_db();click.echo('Platform Management project database initialized.')

    @app.cli.command('seed-pm-demo')
    def seed():
        init_db();seed_projects()

    @app.cli.command('set-pm-password')
    @click.option('--username',default='pm_demo',show_default=True)
    def set_password(username):
        """Choose a new password for an existing active manager account only."""
        rows=RegisteredUser._readAll()
        user=next((u for u in rows if u['username']==username),None)
        if not user or user['role']!='Platform Management' or user['status']!='Active':
            raise click.ClickException('Choose an existing active Platform Management account.')
        password=click.prompt('New manager password (at least 8 characters)',hide_input=True,confirmation_prompt=True)
        if len(password)<8: raise click.ClickException('Password must be at least 8 characters.')
        user['password']=RegisteredUser.hashPassword(password)
        RegisteredUser._writeAll(rows)
        click.echo(f'Password updated for {username}. Sign in through the shared login page.')
