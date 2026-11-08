CREATE TABLE IF NOT EXISTS photos (
          id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          filename TEXT NOT NULL, photo_type TEXT NOT NULL DEFAULT 'After', position INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS company (
          id INTEGER PRIMARY KEY AUTOINCREMENT, designer_id TEXT NOT NULL UNIQUE,
          name TEXT, description TEXT, email TEXT, phone TEXT, location TEXT
        );
        CREATE TABLE IF NOT EXISTS reviews (
          id INTEGER PRIMARY KEY AUTOINCREMENT, designer_id TEXT NOT NULL,
          customer TEXT NOT NULL, review TEXT NOT NULL, reply TEXT DEFAULT ''
        );
