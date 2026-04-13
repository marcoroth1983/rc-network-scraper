# PLAN 015 — User-Specific Favorites (Merkliste)

| Approval | Status | Date |
|----------|--------|------|
| Reviewer | approved | 2026-04-13 |
| Human | approved | 2026-04-13 |

## Context & Goal

The app has three registered users. `is_favorite` and `favorited_at` are currently columns on the `listings` table with no user reference — all users share one global favorites list. This plan migrates to a dedicated `user_favorites` join table so each user has their own independent Merkliste. The API contract exposed to the frontend (`is_favorite: bool`) stays identical; only the storage and computation change.

## Breaking Changes

**Yes.** The `is_favorite` and `favorited_at` columns are dropped from `listings`. The migration seeds all currently-favorited listings into `user_favorites` for the admin user (looked up by email, not hardcoded ID) so no data is lost.

## Reviewer Notes

All 5 blocking issues from first review are addressed in this revision:
1. `get_favorites` preserves `plz` distance-filtering (Step 3d)
2. `test_api.py` explicitly listed with rewrite instructions (Step 5)
3. Test FK constraint addressed — tests must seed a real user row (Step 5)
4. Migration uses email lookup instead of hardcoded `user_id = 1` (Step 1)
5. Old `ADD COLUMN IF NOT EXISTS is_favorite/favorited_at` lines removed from `db.py` (Step 1)

---

## Steps

### Step 1 — DB: New `user_favorites` Table + Column Removal `[open]`

**File: `backend/app/db.py`**

1. **Remove** the existing `ADD COLUMN IF NOT EXISTS` lines for `is_favorite` and `favorited_at` from `init_db()`. Search for these lines and delete them:
   ```python
   # DELETE these two lines wherever they appear in init_db():
   await conn.execute(text("ALTER TABLE listings ADD COLUMN IF NOT EXISTS is_favorite BOOLEAN NOT NULL DEFAULT false"))
   await conn.execute(text("ALTER TABLE listings ADD COLUMN IF NOT EXISTS favorited_at TIMESTAMPTZ"))
   ```

2. **Append** the following block to `init_db()` after all remaining existing migration lines:

```python
# PLAN-015: user-specific favorites
await conn.execute(text("""
    CREATE TABLE IF NOT EXISTS user_favorites (
        user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (user_id, listing_id)
    )
"""))
await conn.execute(text(
    "CREATE INDEX IF NOT EXISTS ix_user_favorites_user_id ON user_favorites (user_id)"
))
# Migrate existing favorites to the admin user (looked up by email, not hardcoded ID)
await conn.execute(text("""
    INSERT INTO user_favorites (user_id, listing_id, created_at)
    SELECT u.id, l.id, COALESCE(l.favorited_at, now())
    FROM listings l
    JOIN users u ON u.email = 'marco.roth1983@googlemail.com'
    WHERE l.is_favorite = TRUE
    ON CONFLICT (user_id, listing_id) DO NOTHING
"""))
# Drop legacy columns (data already migrated above)
await conn.execute(text("ALTER TABLE listings DROP COLUMN IF EXISTS is_favorite"))
await conn.execute(text("ALTER TABLE listings DROP COLUMN IF EXISTS favorited_at"))
```

The entire block is idempotent — `CREATE TABLE IF NOT EXISTS`, `ON CONFLICT DO NOTHING`, `DROP COLUMN IF EXISTS` make it safe to run on every startup.

---

### Step 2 — Model: Add `UserFavorite`, remove legacy fields from `Listing` `[open]`

**File: `backend/app/models.py`**

1. Remove `is_favorite` and `favorited_at` from the `Listing` class.

2. Add after `SearchNotification`:

```python
class UserFavorite(Base):
    __tablename__ = "user_favorites"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    listing_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("listings.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
```

`func` is already imported from `sqlalchemy.sql`. `Integer`, `ForeignKey` are already imported.

---

### Step 3 — Backend: Rewrite Favorite Endpoints + Inject `is_favorite` `[open]`

**File: `backend/app/api/routes.py`**

#### 3a — Imports

Add `UserFavorite` to the `from app.models import ...` line. Add `delete` to sqlalchemy imports if not already present.

#### 3b — Helper (add before route definitions)

```python
async def _get_favorite_listing_ids(user_id: int, session: AsyncSession) -> set[int]:
    """Return set of listing IDs favorited by the given user. One DB round-trip."""
    result = await session.execute(
        select(UserFavorite.listing_id).where(UserFavorite.user_id == user_id)
    )
    return {row for (row,) in result.all()}
```

#### 3c — Rewrite `toggle_favorite`

```python
@router.patch("/listings/{listing_id}/favorite")
async def toggle_favorite(
    listing_id: int,
    is_favorite: bool,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Add or remove a listing from the current user's favorites."""
    exists = await session.execute(select(Listing.id).where(Listing.id == listing_id))
    if exists.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Listing not found")

    if is_favorite:
        await session.execute(
            text("""
                INSERT INTO user_favorites (user_id, listing_id)
                VALUES (:uid, :lid)
                ON CONFLICT (user_id, listing_id) DO NOTHING
            """),
            {"uid": current_user.id, "lid": listing_id},
        )
    else:
        await session.execute(
            delete(UserFavorite).where(
                UserFavorite.user_id == current_user.id,
                UserFavorite.listing_id == listing_id,
            )
        )
    await session.commit()
    return {"id": listing_id, "is_favorite": is_favorite}
```

#### 3d — Rewrite `get_favorites` (preserve PLZ distance filtering)

```python
@router.get("/favorites", response_model=list[ListingSummary])
async def get_favorites(
    plz: str | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[ListingSummary]:
    """Return the current user's favorited listings, newest favorite first."""
    result = await session.execute(
        select(Listing)
        .join(UserFavorite, UserFavorite.listing_id == Listing.id)
        .where(UserFavorite.user_id == current_user.id)
        .order_by(UserFavorite.created_at.desc())
    )
    listings = result.scalars().all()

    if plz:
        pairs = await filter_by_distance(listings, plz, None, session)
        return [
            ListingSummary.model_validate(listing).model_copy(
                update={"is_favorite": True, "distance_km": dist}
            )
            for listing, dist in pairs
        ]

    return [
        ListingSummary.model_validate(l).model_copy(update={"is_favorite": True})
        for l in listings
    ]
```

#### 3e — Inject `is_favorite` into `list_listings`

`list_listings` has multiple code paths that produce `ListingSummary` objects. Read the current implementation carefully — all call sites must be covered.

Add `current_user: User = Depends(get_current_user)` to the function signature. Then fetch `fav_ids` **once** near the top of the function body (after parameter validation, before branching):

```python
fav_ids = await _get_favorite_listing_ids(current_user.id, session)
```

At **every** call site where a `ListingSummary` is created from a listing row, apply:
```python
summary = ListingSummary.model_validate(row)
if row.id in fav_ids:
    summary = summary.model_copy(update={"is_favorite": True})
```

For list comprehensions, expand them into explicit loops so the `fav_ids` check can be applied. Example:
```python
# Before:
items = [ListingSummary.model_validate(r) for r in rows]
# After:
items = []
for r in rows:
    s = ListingSummary.model_validate(r)
    if r.id in fav_ids:
        s = s.model_copy(update={"is_favorite": True})
    items.append(s)
```

Apply the same pattern to `get_listings_by_author` and `get_listing` (detail endpoint).

---

### Step 4 — Schemas `[open]`

`ListingSummary` and `ListingDetail` both declare `is_favorite: bool = False`. Default is correct — no schema changes needed.

---

### Step 5 — Tests `[open]`

**File: `backend/tests/test_api.py`**

This file has breaking changes in two places:

1. **`_insert_listing_full` helper** — currently inserts `is_favorite=True/False` into the `listings` table. Remove the `is_favorite` parameter and all uses. The helper signature becomes: `_insert_listing_full(conn, listing_id, ...) → None` without `is_favorite`.

2. **`TestFavorites` class** — currently sets up test data using `is_favorite=True` on listings. Rewrite to:
   - Seed a real `users` row in the DB (the FK on `user_favorites` requires it). Use the pattern from `test_saved_searches.py` which already seeds a user.
   - Override `get_current_user` to return a `User` with the seeded `user_id`.
   - Insert test favorites directly into `user_favorites` table rather than via `listings.is_favorite`.
   - Assert that `GET /api/favorites` returns only the listings favorited by the current user.
   - Assert that `PATCH /api/listings/{id}/favorite?is_favorite=true` inserts into `user_favorites`.
   - Assert that `PATCH /api/listings/{id}/favorite?is_favorite=false` removes from `user_favorites`.

---

## Verification

```bash
# 1. Migration: new table exists, old columns gone
docker compose exec db psql -U rcscout -d rcscout -c "\d user_favorites"
docker compose exec db psql -U rcscout -d rcscout -c "\d listings" | grep -E "is_favorite|favorited_at"
# Expected: user_favorites described; nothing for is_favorite/favorited_at

# 2. Marco's favorites migrated
docker compose exec db psql -U rcscout -d rcscout -c \
  "SELECT COUNT(*) FROM user_favorites WHERE user_id = 1;"

# 3. Backend tests
docker compose exec backend pytest tests/ -v

# 4. Frontend build
cd frontend && npm run build
```

## Files Changed

| File | Change |
|------|--------|
| `backend/app/db.py` | Remove old ADD COLUMN lines; add CREATE TABLE, migration INSERT, DROP COLUMN |
| `backend/app/models.py` | Remove `is_favorite`/`favorited_at` from `Listing`; add `UserFavorite` model |
| `backend/app/api/routes.py` | Rewrite `toggle_favorite`, `get_favorites`; add `_get_favorite_listing_ids` helper; inject per-user `is_favorite` into `list_listings`, `get_listing`, `get_listings_by_author` |
| `backend/app/api/schemas.py` | No changes |
| `backend/tests/test_api.py` | Rewrite `_insert_listing_full` (remove `is_favorite`); rewrite `TestFavorites` to use `user_favorites` table |
| `frontend/src/types/api.ts` | No changes |
| `frontend/src/api/client.ts` | No changes |
