# JARVIS Versioning Policy

> **Effective**: v0.9.0+  
> **Standard**: Semantic Versioning 2.0.0

---

## Version Format

```
MAJOR.MINOR.PATCH
```

| Component | When to Increment |
|-----------|-------------------|
| **MAJOR** | Breaking changes to stable API or invariants |
| **MINOR** | New features (backward compatible) |
| **PATCH** | Bug fixes, documentation, internal changes |

---

## What Constitutes a Breaking Change

### Definitely Breaking (Requires MAJOR)

- Removing a STABLE export
- Changing function signature (required args)
- Changing return type
- Removing invariant guarantee
- Changing behavior of STABLE method

### Not Breaking (MINOR or PATCH)

- Adding new exports
- Adding optional parameters
- Improving error messages
- Performance improvements
- Internal refactoring
- Documentation updates

---

## Deprecation Policy

1. **Announce**: Deprecation warning for at least one MINOR version
2. **Document**: Deprecation noted in CHANGELOG
3. **Remove**: Only in next MAJOR version

```python
import warnings

def deprecated_method(self):
    warnings.warn(
        "deprecated_method() is deprecated since v0.9.0, "
        "use new_method() instead. Will be removed in v1.0.0.",
        DeprecationWarning,
        stacklevel=2
    )
```

---

## Configuration Stability

As of v0.9.0:

- **Unknown configuration keys are errors**
- Configuration schema changes follow same rules as API
- New optional config keys = MINOR
- Removing config keys = MAJOR

---

## Pre-1.0 Stability

While version < 1.0.0:

- MINOR versions may contain breaking changes
- This document takes precedence over SemVer defaults
- All STABLE markers are still binding

After v1.0.0:

- Full SemVer compliance
- No breaking changes without MAJOR bump
- Minimum 1 version deprecation cycle

---

## Release Checklist

Before any release:

- [ ] All tests pass
- [ ] CHANGELOG updated
- [ ] Version bumped in `pyproject.toml`
- [ ] API.md reflects changes
- [ ] INVARIANTS.md unchanged (or MAJOR bump)
