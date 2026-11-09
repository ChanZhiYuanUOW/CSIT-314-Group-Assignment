"""Map temporary project records into Zhiyuan's existing homepage card contract."""
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
    return [dict(idp_id=p['id'],title=p['title'],designer=users.get(str(p['designer_id']),{}).get('full_name','Designer'),style=p['category'],property_type='Demo project',estimated_cost_sgd='Not provided',views_count=counts.get(p['id'],{}).get('views',0),shortlist_count=counts.get(p['id'],{}).get('shortlists',0),image_url='') for p in projects]
