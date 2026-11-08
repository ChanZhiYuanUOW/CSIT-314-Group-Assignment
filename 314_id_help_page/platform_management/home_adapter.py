"""Map temporary project records into Zhiyuan's existing homepage card contract."""
from .db import get_db
from .entities import PlatformData


def featured_home_cards():
    db=get_db()
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='projects'").fetchone():
        return []
    users=PlatformData.users()
    from .workflow_entities import WorkflowEntity
    projects=WorkflowEntity.activeFeatured()
    counts={r['project_id']:r for r in PlatformData.rows("SELECT project_id,SUM(kind='view') AS views,SUM(kind='shortlist') AS shortlists FROM engagement_events GROUP BY project_id")}
    return [dict(idp_id=p['id'],title=p['title'],designer=users.get(str(p['designer_id']),{}).get('full_name','Designer'),style=p['category'],property_type='Demo project',estimated_cost_sgd='Not provided',views_count=counts.get(p['id'],{}).get('views',0),shortlist_count=counts.get(p['id'],{}).get('shortlists',0),image_url='') for p in projects]
