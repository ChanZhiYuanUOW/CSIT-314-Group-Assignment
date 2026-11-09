"""Customer features (BCE): browse/search/filter, project details, compare, report, share,
recently viewed and personalised recommendations.

Register with:  from customer_features import init_app;  init_app(app)

Storage: everything is CSV. Projects, categories, photos, company profiles, reviews, engagement events and
content reports are the group's shared CsvStore tables (data/platform/*.csv); the customer's viewing history is
data/platform/recently_viewed.csv. Accounts come from data/registered_users.csv and are never written here.
"""


def init_app(app):
    from .boundaries import bp
    app.register_blueprint(bp, url_prefix='/customer')
