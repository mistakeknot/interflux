# server.js — User Search Endpoint

```javascript
const express = require("express");
const mysql = require("mysql2");
const app = express();

const db = mysql.createPool({
  host: "localhost",
  user: "app",
  password: process.env.DB_PASSWORD,
  database: "production",
});

app.use(express.json());

app.get("/api/users", (req, res) => {
  const { name, role } = req.query;

  const query = `SELECT id, name, email, role FROM users WHERE name LIKE '%${name}%' AND role = '${role}'`;

  db.query(query, (err, results) => {
    if (err) {
      console.error("Database error:", err);
      return res.status(500).json({
        error: err.message,
        stack: err.stack,
        query: query,
      });
    }

    res.json({ users: results, count: results.length });
  });
});

app.listen(3000, () => {
  console.log("Server running on port 3000");
});
```
