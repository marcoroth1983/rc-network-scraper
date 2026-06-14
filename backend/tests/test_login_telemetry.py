"""Tests for login_events table and saved_searches FK cascade (PLAN-033)."""

import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_login_events_table_exists_and_cascades(db_session):
    # login_events row is removed when its user is deleted (ON DELETE CASCADE)
    await db_session.execute(text(
        "INSERT INTO users (google_id, email, name, is_approved, role) "
        "VALUES ('le-g', 'le@example.com', 'LE', TRUE, 'member')"
    ))
    uid = (await db_session.execute(
        text("SELECT id FROM users WHERE google_id = 'le-g'")
    )).scalar_one()
    await db_session.execute(
        text("INSERT INTO login_events (user_id) VALUES (:u)"), {"u": uid}
    )
    await db_session.commit()
    assert (await db_session.execute(
        text("SELECT count(*) FROM login_events WHERE user_id = :u"), {"u": uid}
    )).scalar_one() == 1

    await db_session.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})
    await db_session.commit()
    assert (await db_session.execute(
        text("SELECT count(*) FROM login_events WHERE user_id = :u"), {"u": uid}
    )).scalar_one() == 0


@pytest.mark.asyncio
async def test_saved_searches_cascade_on_user_delete(db_session):
    # deleting a user removes their saved_searches (FK cascade fix)
    await db_session.execute(text(
        "INSERT INTO users (google_id, email, name, is_approved, role) "
        "VALUES ('ss-g', 'ss@example.com', 'SS', TRUE, 'member')"
    ))
    uid = (await db_session.execute(
        text("SELECT id FROM users WHERE google_id = 'ss-g'")
    )).scalar_one()
    await db_session.execute(
        text("INSERT INTO saved_searches (user_id, name) VALUES (:u, 'x')"), {"u": uid}
    )
    await db_session.commit()
    await db_session.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})
    await db_session.commit()
    assert (await db_session.execute(
        text("SELECT count(*) FROM saved_searches WHERE user_id = :u"), {"u": uid}
    )).scalar_one() == 0
