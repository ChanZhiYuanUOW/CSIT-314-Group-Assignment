"""Entity layer for the customer features, built on the group's shared CSV store (CsvStore).

All persistence goes through platform_management.db.get_db(), so this module follows the same rules as
Platform Management and the designer portfolio: one file lock per request, atomic multi-table saves.

Shared tables reused (data/platform/*.csv):
  projects, categories, photos, company, reviews     -> read only
  engagement_events                                  -> customer 'view' rows are appended
  content_reports                                    -> customer reports are appended (status 'open')
Owned by this module:
  data/platform/recently_viewed.csv                  -> per-customer browsing history
Customer / designer accounts come from the shared CSV via PlatformData.users() (never written here).

Rows returned by CsvStore are the live in-memory dicts, so every function below copies before adding fields.
"""
import csv
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from platform_management.db import get_db
from platform_management.entities import PlatformData, utc_now

SORTS = ('newest', 'oldest', 'popular', 'title')


def _split_tags(raw):
    return [t.strip() for t in (raw or '').replace(';', ',').split(',') if t.strip()]


def style_of(category_name):
    """The design style of a category = its first word ('Modern Kitchen' -> 'Modern')."""
    parts = (category_name or '').split()
    return parts[0] if parts else ''


def _build_cards(published_only=True):
    """Every project as a display card: category, designer name, company, cover photo, view count, tags."""
    db = get_db()
    categories = {c['id']: c['name'] for c in db.all('categories')}
    views = Counter(e['project_id'] for e in db.all('engagement_events') if e['kind'] == 'view')
    companies = {c['designer_id']: c['name'] for c in db.all('company')}
    cover = {}
    for ph in sorted(db.all('photos'), key=lambda p: (p['position'], p['id']), reverse=True):
        cover[ph['project_id']] = ph['filename']  # reversed sort, so the first photo wins
    users = PlatformData.users()
    cards = []
    for p in db.all('projects'):
        if published_only and p['status'] != 'published':
            continue
        user = users.get(str(p['designer_id']))
        card = dict(p)
        card.update(category=categories.get(p['category_id'], 'Uncategorised'),
                    views=views.get(p['id'], 0),
                    company_name=companies.get(p['designer_id'], ''),
                    style=style_of(categories.get(p['category_id'], '')),
                    cover=cover.get(p['id']),
                    designer=user['full_name'] if user else 'Designer',
                    tag_list=_split_tags(p.get('tags')))
        cards.append(card)
    return cards


def _sort(cards, sort):
    if sort == 'oldest':
        return sorted(cards, key=lambda c: (c['created_at'], c['id']))
    if sort == 'popular':
        return sorted(cards, key=lambda c: (c['views'], c['id']), reverse=True)
    if sort == 'title':
        return sorted(cards, key=lambda c: (c['title'].casefold(), c['id']))
    return sorted(cards, key=lambda c: (c['created_at'], c['id']), reverse=True)  # newest


class ProjectCatalogue:
    """<<entity>> :ProjectCatalogue - read-only view over published projects."""

    @staticmethod
    def categories():
        """Design styles (first word of the category name, e.g. Modern, Rustic) that currently have at least
        one published project, with the number of published projects in each (for the filter drop-down)."""
        names = {c['id']: c['name'] for c in get_db().all('categories')}
        counts = Counter(style_of(names[p['category_id']]) for p in get_db().all('projects')
                         if p['status'] == 'published' and p['category_id'] in names)
        rows = [{'id': style, 'name': style, 'project_count': n} for style, n in counts.items() if style]
        return sorted(rows, key=lambda c: c['name'].casefold())

    @classmethod
    def search(cls, keyword='', category_ids=(), sort='newest', page=1, per_page=12, styles=()):
        """Keyword + category/style search over published projects.

        Every whitespace-separated keyword must appear in at least one of: title, description, tags,
        category name, company name or designer name (AND across words, OR across fields).
        """
        tokens = [t.casefold()[:60] for t in keyword.strip().split() if t][:8]
        wanted = {int(c) for c in category_ids}
        wanted_styles = {str(x).casefold() for x in styles if str(x).strip()}
        matches = []
        for card in _build_cards():
            if wanted and card['category_id'] not in wanted:
                continue
            if wanted_styles and card['style'].casefold() not in wanted_styles:
                continue
            if tokens:
                haystack = ' '.join([card['title'], card['description'], card['tags'] or '', card['category'],
                                     card['company_name'], card['designer']]).casefold()
                if not all(token in haystack for token in tokens):
                    continue
            matches.append(card)
        ordered = _sort(matches, sort if sort in SORTS else 'newest')
        start = (page - 1) * per_page
        return ordered[start:start + per_page], len(ordered)

    @classmethod
    def published_cards(cls, ids):
        """Card rows for the given ids, published only, in the order requested."""
        wanted = [int(i) for i in ids]
        if not wanted:
            return []
        by_id = {c['id']: c for c in _build_cards() if c['id'] in set(wanted)}
        return [by_id[i] for i in wanted if i in by_id]

    @classmethod
    def all_published_cards(cls, limit=500):
        return _sort(_build_cards(), 'newest')[:limit]

    @classmethod
    def published_detail(cls, project_id):
        """Full detail record for one published project, or None if missing / not public."""
        found = cls.published_cards([project_id])
        if not found:
            return None
        item = found[0]
        db = get_db()
        item['photos'] = [dict(p) for p in sorted(db.all('photos', project_id=item['id']), key=lambda p: (p['position'], p['id']))]
        company = db.first('company', designer_id=item['designer_id'])
        fields = ('name', 'description', 'email', 'phone', 'location')
        item['company'] = {k: company[k] for k in fields} if company and any(company[k] for k in fields) else None
        reviews = sorted(db.all('reviews', designer_id=item['designer_id']), key=lambda r: r['id'], reverse=True)
        item['reviews'] = [{k: r[k] for k in ('customer', 'review', 'reply')} for r in reviews[:5]]
        item['review_count'] = len(reviews)
        item['photo_count'] = len(item['photos'])
        return item


class RecentlyViewed:
    """<<entity>> :RecentlyViewed - per-customer browsing history, stored in data/platform/recently_viewed.csv.

    Lives next to the shared tables. Calling get_db() first takes the same file lock the shared store uses,
    so this file is protected exactly like the others; writes are atomic (temp file + replace)."""
    FILE_NAME = 'recently_viewed.csv'
    FIELDS = ['customer_id', 'project_id', 'viewed_at']
    LIMIT = 20

    @classmethod
    def _path(cls):
        return get_db().folder / cls.FILE_NAME  # get_db() also acquires the shared lock

    @classmethod
    def _readAll(cls):
        path = cls._path()
        if not path.exists():
            return []
        with path.open(encoding='utf-8-sig', newline='') as f:
            return [r for r in csv.DictReader(f) if r.get('customer_id') and r.get('project_id', '').isdigit()]

    @classmethod
    def _writeAll(cls, rows):
        path = cls._path()
        tmp = path.with_name(path.name + '.tmp')
        with tmp.open('w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=cls.FIELDS)
            writer.writeheader()
            writer.writerows(rows)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    @classmethod
    def record(cls, customer_id, project_id):
        stamp = datetime.now(timezone.utc).isoformat(timespec='microseconds')
        cid, pid = str(customer_id), str(project_id)
        rows = [r for r in cls._readAll() if not (r['customer_id'] == cid and r['project_id'] == pid)]
        rows.append({'customer_id': cid, 'project_id': pid, 'viewed_at': stamp})
        mine = sorted((r for r in rows if r['customer_id'] == cid), key=lambda r: r['viewed_at'], reverse=True)
        drop = {id(r) for r in mine[cls.LIMIT:]}
        cls._writeAll([r for r in rows if id(r) not in drop])

    @classmethod
    def ids(cls, customer_id, limit=LIMIT):
        mine = [r for r in cls._readAll() if r['customer_id'] == str(customer_id)]
        mine.sort(key=lambda r: r['viewed_at'], reverse=True)
        return [int(r['project_id']) for r in mine[:limit]]

    @classmethod
    def remove(cls, customer_id, project_id):
        rows = cls._readAll()
        kept = [r for r in rows if not (r['customer_id'] == str(customer_id) and r['project_id'] == str(project_id))]
        if len(kept) != len(rows):
            cls._writeAll(kept)
        return len(rows) - len(kept)

    @classmethod
    def clear(cls, customer_id):
        rows = cls._readAll()
        kept = [r for r in rows if r['customer_id'] != str(customer_id)]
        if len(kept) != len(rows):
            cls._writeAll(kept)
        return len(rows) - len(kept)


class EngagementLog:
    """<<entity>> :EngagementLog - writes 'view' rows into the shared engagement_events.csv so Platform
    Management analytics also count customer views, and reads them back for recommendations."""

    @staticmethod
    def record_view(customer_id, project_id, dedupe_minutes=30):
        """Append a view event unless this customer already viewed this project very recently."""
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=dedupe_minutes)).isoformat(timespec='seconds')
        with get_db() as db:
            if any(e['occurred_at'] >= cutoff for e in db.all('engagement_events', customer_id=str(customer_id),
                                                                project_id=int(project_id), kind='view')):
                return False
            db.add('engagement_events', project_id=int(project_id), customer_id=str(customer_id),
                   kind='view', occurred_at=utc_now())
            return True

    @staticmethod
    def history(customer_id):
        """[{category_id, category, tags, kind, n}] for this customer's engagement with published projects."""
        db = get_db()
        projects = {p['id']: p for p in db.all('projects') if p['status'] == 'published'}
        names = {c['id']: c['name'] for c in db.all('categories')}
        grouped = Counter()
        for e in db.all('engagement_events', customer_id=str(customer_id)):
            p = projects.get(e['project_id'])
            if p:
                grouped[(p['category_id'], p['tags'] or '', e['kind'])] += 1
        return [{'category_id': cid, 'category': names.get(cid, ''), 'tags': tags, 'kind': kind, 'n': n}
                for (cid, tags, kind), n in grouped.items()]


class ProjectReport:
    """<<entity>> :ProjectReport - customer submissions into the shared content_reports.csv queue."""

    @staticmethod
    def has_open(reporter_id, project_id, reason):
        return get_db().first('content_reports', reporter_id=str(reporter_id), project_id=int(project_id),
                              reason=reason, status='open') is not None

    @staticmethod
    def count_since(reporter_id, since_iso):
        return sum(1 for r in get_db().all('content_reports', reporter_id=str(reporter_id))
                   if r['created_at'] >= since_iso)

    @staticmethod
    def create(reporter_id, project_id, reason, evidence):
        with get_db() as db:
            return db.add('content_reports', project_id=int(project_id), reporter_id=str(reporter_id), reason=reason,
                          evidence=evidence, status='open', created_at=utc_now())['id']
