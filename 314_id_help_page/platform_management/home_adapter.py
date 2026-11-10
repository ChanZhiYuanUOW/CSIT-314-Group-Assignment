"""Map temporary project records into Zhiyuan's existing homepage card contract."""
from flask import current_app, session, url_for

from .db import get_db
from .entities import PlatformData


def featured_home_cards():
    db=get_db()
    users=PlatformData.users()
    from .workflow_entities import WorkflowEntity
    projects=WorkflowEntity.activeFeatured()
    counts = {}
    for event in db.all('engagement_events'):
        count = counts.setdefault(event['project_id'], {'views':0, 'shortlist':0})
        count['views' if event['kind']=='view' else 'shortlist'] += 1
    covers = {}
    for photo in sorted(db.all('photos'), key=lambda row: (row['position'], row['id'])):
        covers.setdefault(photo['project_id'], photo['filename'])

    endpoint = 'customer.viewProjectDetails' if session.get('role') == 'Customer' else 'customer.publicProject'
    cards = []
    for project in projects:
        project_id = project['id']
        filename = covers.get(project_id)
        totals = counts.get(project_id, {})
        cards.append(dict(
            idp_id=project_id,
            detail_url=url_for(endpoint, project_id=project_id) if endpoint in current_app.view_functions else '',
            title=project['title'],
            designer=users.get(str(project['designer_id']), {}).get('full_name', 'Designer'),
            style=project['category'],
            property_type='Demo project',
            estimated_cost_sgd=project['estimated_cost_sgd'],
            views_count=totals.get('views', 0),
            shortlist_count=totals.get('shortlist', 0),
            image_url=url_for('designer.static', filename='uploads/' + filename) if filename else '',
        ))
    return cards
