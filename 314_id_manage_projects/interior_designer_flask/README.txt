INTERIOR DESIGNER FLASK - PORTFOLIO WORKSPACE

This app supports the interior designer's responsibilities:
- Manage Project Portfolio (view status, edit/delete eligible listings)
- Maintain Company Profile
- Create New Project Listing (metadata, photos, gallery ordering and preview)
- Reply to Customer Review
- View projects hidden by platform management in the portfolio

PROJECT DATA / PLATFORM MANAGEMENT INTEGRATION

Each project uses the same core fields as the CSIT314 platform-management app:
- projects.id: project ID (the shared project identifier)
- projects.designer_id: registered user ID of the owning designer
- projects.category_id: category foreign key into categories
- projects.status: draft, published, hidden, or removed
- projects.restriction_version: moderation version maintained by platform management

The designer workspace never deletes a project just because platform management hides it.
Hidden/removed projects remain visible to their owner in the dashboard. They are not editable,
republishable, or deletable by the designer while restricted. The platform-management app
controls moderation decisions. Its customer-facing project queries should show only
projects with status='published'.

CONFIGURATION

For a standalone demo, run with the local database.db:
    py -m pip install -r requirements.txt
    py app.py

To share projects with the platform-management Flask app, point both apps at the SAME SQLite file.
The platform-management app defaults to:
    <platform-management folder>/instance/platform_management.sqlite3
Set these environment variables before starting the designer app (PowerShell example):
    $env:PLATFORM_DATABASE = "C:\\path\\to\\platform-management\\instance\\platform_management.sqlite3"
    $env:DESIGNER_USER_ID = "<exact registered_users.user_id for this designer>"
    py app.py

DESIGNER_USER_ID must match the designer_id stored by platform management. The default
"designer_demo" is only a local demo identity; replace it for integration.

IMPORTANT AUTHENTICATION NOTE
This supplied designer Flask project did not include authentication. To avoid pretending that
it has verified a login, this version takes the designer identity from DESIGNER_USER_ID.
For a real integrated deployment, set that value from the authenticated session (not from a
user-editable form or URL), and share the platform-management database file. Do not run two
separate copies of the database if the apps are expected to share moderation status.

The app creates/upgrades its tables additively and preserves existing project/photo data where
possible. Uploaded photos remain in static/uploads. Change FLASK_SECRET_KEY before deployment.
