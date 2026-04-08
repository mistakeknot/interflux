# app.py — User Profile Loader

```python
import json


def load_user_profile(user_id, config):
    db = config.get("database")
    connection = db.connect()

    cursor = connection.execute(
        "SELECT profile_data FROM users WHERE id = ?", (user_id,)
    )
    row = cursor.fetchone()

    profile = json.loads(row[0])

    preferences = profile["settings"]["notifications"]

    with open(f"/tmp/cache/{user_id}.json", "w") as f:
        json.dump(profile, f)

    return {
        "user_id": user_id,
        "name": profile["name"],
        "email": profile["email"],
        "preferences": preferences,
    }
```
