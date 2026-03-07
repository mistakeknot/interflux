# Testing & Validation

## Test Suites

```bash
# Run all structural tests (103 tests)
cd /root/projects/Interverse/plugins/interflux && uv run pytest tests/ -q

# Key test suites
uv run pytest tests/structural/test_namespace.py -v  # Guards against stale clavain: refs
uv run pytest tests/structural/test_agents.py -v     # Agent structure validation
uv run pytest tests/structural/test_skills.py -v     # Skill structure validation
uv run pytest tests/structural/test_slicing.py -v    # Content routing tests
```

## Validation Checklist

```bash
# Count components
ls agents/review/*.md | wc -l         # Should be 8
ls agents/research/*.md | wc -l       # Should be 5
ls commands/*.md | wc -l              # Should be 3
ls skills/*/SKILL.md | wc -l          # Should be 2

# Domain profiles
grep -l '## Research Directives' config/flux-drive/domains/*.md | wc -l  # Should be 11

# Manifest
python3 -c "import json; d=json.load(open('.claude-plugin/plugin.json')); print(list(d['mcpServers'].keys()))"  # ['exa']

# Namespace check — no stale clavain: references
uv run pytest tests/structural/test_namespace.py -v
```
